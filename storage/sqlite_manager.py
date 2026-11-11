"""
storage/sqlite_manager.py

Persistent local source of truth for the Autonomous Lake Cleaning Bot.

Tables:
  missions          — mission metadata, status, progress, cloud-sync versioning
  mission_waypoints — ordered waypoints (GCS -> polygon traversal -> GCS)
  sensor_records    — one GPS-tagged sensor snapshot per 10 s, upload queue

WAL mode + a single shared connection guarded by an RLock: safe for the
multi-threaded service and resilient to power loss / reboots.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)

MISSION_STATUSES = (
    "PENDING", "LOADING_WAYPOINTS", "READY", "ACTIVE",
    "PAUSED", "COMPLETED", "ABORTED", "FAILED",
)
TERMINAL_STATUSES = ("COMPLETED", "ABORTED", "FAILED")
SYNC_STATUSES = ("PENDING", "SYNCED", "FAILED")
# Same values as Supabase mission_waypoints.status (docs/supabase_schema.webp).
WAYPOINT_STATUSES = ("PENDING", "ACTIVE", "COMPLETED", "SKIPPED")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS missions (
    mission_id              TEXT PRIMARY KEY,
    device_id               TEXT NOT NULL,
    lake_id                 TEXT,
    status                  TEXT NOT NULL CHECK (status IN {MISSION_STATUSES}),
    payload_hash            TEXT NOT NULL,
    gcs_latitude            REAL NOT NULL,
    gcs_longitude           REAL NOT NULL,
    polygon_json            TEXT NOT NULL,
    total_waypoints         INTEGER NOT NULL DEFAULT 0,
    current_waypoint_index  INTEGER NOT NULL DEFAULT 0,
    progress_percent        REAL NOT NULL DEFAULT 0,
    waypoint_load_ack       INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    loaded_at               TEXT,
    started_at              TEXT,
    completed_at            TEXT,
    updated_at              TEXT NOT NULL,
    notes                   TEXT,
    cloud_version           INTEGER NOT NULL DEFAULT 1,
    cloud_synced_version    INTEGER NOT NULL DEFAULT 0,
    waypoints_cloud_synced  INTEGER NOT NULL DEFAULT 0,
    last_sync_error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
CREATE INDEX IF NOT EXISTS idx_missions_sync ON missions(cloud_version, cloud_synced_version);

CREATE TABLE IF NOT EXISTS mission_waypoints (
    mission_id      TEXT NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    sequence_order  INTEGER NOT NULL,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    waypoint_type   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN {WAYPOINT_STATUSES}),
    reached_at      TEXT,
    cloud_dirty     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (mission_id, sequence_order)
);

CREATE TABLE IF NOT EXISTS sensor_records (
    local_record_id     TEXT NOT NULL UNIQUE,
    mission_id          TEXT,
    device_id           TEXT NOT NULL,
    recorded_at         TEXT NOT NULL,
    hardware_timestamp  TEXT,
    latitude            REAL,
    longitude           REAL,
    heading             REAL,
    gps_valid           INTEGER NOT NULL DEFAULT 0,
    gps_age_seconds     REAL,
    ph                  REAL,
    tds                 REAL,
    turbidity           REAL,
    temperature_c       REAL,
    humidity_percent    REAL,
    sync_status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (sync_status IN {SYNC_STATUSES}),
    retry_count         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at     REAL,
    last_upload_attempt TEXT,
    last_upload_error   TEXT,
    synced_at           TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sensor_records_pending
    ON sensor_records(sync_status, recorded_at);
CREATE INDEX IF NOT EXISTS idx_sensor_records_mission
    ON sensor_records(mission_id, recorded_at);
"""


def now_iso() -> str:
    """UTC ISO-8601 with milliseconds, e.g. 2026-11-05T10:41:00.000Z"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class SQLiteManager:
    def __init__(self, path: Optional[str] = None):
        self._path = path or settings.SQLITE_PATH
        if self._path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        logger.info("SQLite schema initialized at %s", self._path)

    @property
    def path(self) -> str:
        return self._path

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def ping(self) -> bool:
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ==================================================================
    # Missions
    # ==================================================================
    def create_mission_with_waypoints(self, *, mission_id: str, device_id: str,
                                      lake_id: Optional[str], payload_hash: str,
                                      gcs: tuple[float, float], polygon: list[dict],
                                      waypoints: list[dict], notes: Optional[str] = None) -> None:
        """
        Atomically insert the mission (status LOADING_WAYPOINTS) and all
        ordered waypoints.  Raises sqlite3.IntegrityError on duplicate id.
        """
        ts = now_iso()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO missions (mission_id, device_id, lake_id, status, payload_hash,
                       gcs_latitude, gcs_longitude, polygon_json, total_waypoints,
                       created_at, updated_at, notes)
                   VALUES (?, ?, ?, 'LOADING_WAYPOINTS', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mission_id, device_id, lake_id, payload_hash, gcs[0], gcs[1],
                 json.dumps(polygon, separators=(",", ":")), len(waypoints), ts, ts, notes),
            )
            cur.executemany(
                """INSERT INTO mission_waypoints
                   (mission_id, sequence_order, latitude, longitude, waypoint_type)
                   VALUES (?, ?, ?, ?, ?)""",
                [(mission_id, w["sequence_order"], w["latitude"], w["longitude"], w["type"])
                 for w in waypoints],
            )

    def update_mission(self, mission_id: str, **fields) -> None:
        """Update mission columns and bump cloud_version (so it is re-synced)."""
        if not fields:
            return
        if "status" in fields and fields["status"] not in MISSION_STATUSES:
            raise ValueError(f"invalid mission status {fields['status']!r}")
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE missions SET {cols}, cloud_version = cloud_version + 1 WHERE mission_id = ?",
                (*fields.values(), mission_id),
            )

    def get_mission(self, mission_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,))
            row = cur.fetchone()
        return self._mission_row(row)

    def list_missions(self, statuses: Optional[Iterable[str]] = None, limit: int = 50) -> list[dict]:
        with self._cursor() as cur:
            if statuses:
                statuses = list(statuses)
                marks = ",".join("?" * len(statuses))
                cur.execute(
                    f"SELECT * FROM missions WHERE status IN ({marks}) ORDER BY created_at DESC LIMIT ?",
                    (*statuses, limit),
                )
            else:
                cur.execute("SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (limit,))
            return [self._mission_row(r) for r in cur.fetchall()]

    @staticmethod
    def _mission_row(row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        d["polygon"] = json.loads(d.pop("polygon_json") or "[]")
        d["waypoint_load_ack"] = bool(d["waypoint_load_ack"])
        return d

    def get_waypoints(self, mission_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT sequence_order, latitude, longitude, waypoint_type AS type, status, reached_at
                   FROM mission_waypoints WHERE mission_id = ? ORDER BY sequence_order ASC""",
                (mission_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def count_waypoints(self, mission_id: str) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM mission_waypoints WHERE mission_id = ?", (mission_id,))
            return cur.fetchone()["c"]

    def set_waypoint_active(self, mission_id: str, sequence_order: int) -> None:
        """Mark the current navigation target ACTIVE (any other ACTIVE -> PENDING)."""
        with self._cursor() as cur:
            cur.execute(
                """UPDATE mission_waypoints SET status = 'PENDING', cloud_dirty = 1
                   WHERE mission_id = ? AND status = 'ACTIVE' AND sequence_order != ?""",
                (mission_id, sequence_order),
            )
            cur.execute(
                """UPDATE mission_waypoints SET status = 'ACTIVE', cloud_dirty = 1
                   WHERE mission_id = ? AND sequence_order = ? AND status IN ('PENDING','ACTIVE')""",
                (mission_id, sequence_order),
            )

    def record_waypoint_reached(self, mission_id: str, sequence_order: int,
                                next_index: int, progress_percent: float) -> None:
        """Reached waypoint -> COMPLETED; next target -> ACTIVE; mission progress updated."""
        ts = now_iso()
        with self._cursor() as cur:
            cur.execute(
                """UPDATE mission_waypoints SET status = 'COMPLETED', reached_at = ?, cloud_dirty = 1
                   WHERE mission_id = ? AND sequence_order = ?""",
                (ts, mission_id, sequence_order),
            )
            cur.execute(
                """UPDATE mission_waypoints SET status = 'ACTIVE', cloud_dirty = 1
                   WHERE mission_id = ? AND sequence_order = ? AND status = 'PENDING'""",
                (mission_id, next_index),
            )
            cur.execute(
                """UPDATE missions SET current_waypoint_index = ?, progress_percent = ?,
                       updated_at = ?, cloud_version = cloud_version + 1
                   WHERE mission_id = ?""",
                (next_index, progress_percent, ts, mission_id),
            )

    # ---- cloud sync bookkeeping -------------------------------------
    def missions_needing_sync(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT * FROM missions
                   WHERE cloud_synced_version < cloud_version
                     AND status NOT IN ('PENDING', 'LOADING_WAYPOINTS')
                   ORDER BY updated_at ASC LIMIT ?""",
                (limit,),
            )
            return [self._mission_row(r) for r in cur.fetchall()]

    def mark_mission_synced(self, mission_id: str, version: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                """UPDATE missions SET cloud_synced_version = MAX(cloud_synced_version, ?),
                       last_sync_error = NULL WHERE mission_id = ?""",
                (version, mission_id),
            )

    def mark_waypoints_synced(self, mission_id: str, sent: Optional[list[dict]] = None) -> None:
        """Clear dirty flags for the rows that were sent (unless they changed since)."""
        with self._cursor() as cur:
            cur.execute("UPDATE missions SET waypoints_cloud_synced = 1 WHERE mission_id = ?", (mission_id,))
            if sent is not None:
                cur.executemany(
                    """UPDATE mission_waypoints SET cloud_dirty = 0
                       WHERE mission_id = ? AND sequence_order = ? AND status = ?""",
                    [(mission_id, w["sequence_order"], w["status"]) for w in sent],
                )

    def dirty_waypoints(self, mission_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT sequence_order, latitude, longitude, waypoint_type AS type, status, reached_at
                   FROM mission_waypoints WHERE mission_id = ? AND cloud_dirty = 1
                   ORDER BY sequence_order ASC""",
                (mission_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_mission_sync_error(self, mission_id: str, error: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE missions SET last_sync_error = ? WHERE mission_id = ?",
                        (str(error)[:500], mission_id))

    # ==================================================================
    # Sensor records (10 s snapshots + upload queue)
    # ==================================================================
    def insert_sensor_record(self, record: dict) -> None:
        cols = ("local_record_id", "mission_id", "device_id", "recorded_at", "hardware_timestamp",
                "latitude", "longitude", "heading", "gps_valid", "gps_age_seconds",
                "ph", "tds", "turbidity", "temperature_c", "humidity_percent")
        with self._cursor() as cur:
            cur.execute(
                f"""INSERT INTO sensor_records ({", ".join(cols)}, sync_status, retry_count, created_at)
                    VALUES ({", ".join("?" * len(cols))}, 'PENDING', 0, ?)""",
                (*(record.get(c) for c in cols), now_iso()),
            )

    def get_sensor_record(self, local_record_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM sensor_records WHERE local_record_id = ?", (local_record_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def next_record_to_upload(self, now: Optional[float] = None) -> Optional[dict]:
        """
        Oldest (recorded_at) PENDING/FAILED record whose retry back-off has
        elapsed.  Records of a mission not yet present in the cloud are held
        back so the mission foreign key is always satisfied.
        """
        now = time.time() if now is None else now
        max_retries = settings.UPLOAD_MAX_RETRIES
        with self._cursor() as cur:
            cur.execute(
                """SELECT r.* FROM sensor_records r
                   LEFT JOIN missions m ON m.mission_id = r.mission_id
                   WHERE r.sync_status IN ('PENDING','FAILED')
                     AND (r.next_attempt_at IS NULL OR r.next_attempt_at <= ?)
                     AND (? = 0 OR r.retry_count < ?)
                     AND (r.mission_id IS NULL OR m.cloud_synced_version > 0)
                   ORDER BY r.recorded_at ASC LIMIT 1""",
                (now, max_retries, max_retries),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def mark_record_synced(self, local_record_id: str) -> None:
        ts = now_iso()
        with self._cursor() as cur:
            cur.execute(
                """UPDATE sensor_records SET sync_status = 'SYNCED', synced_at = ?,
                       last_upload_attempt = ?, last_upload_error = NULL, next_attempt_at = NULL
                   WHERE local_record_id = ?""",
                (ts, ts, local_record_id),
            )

    def mark_record_failed(self, local_record_id: str, error: str, next_attempt_at: float) -> None:
        with self._cursor() as cur:
            cur.execute(
                """UPDATE sensor_records SET sync_status = 'FAILED', retry_count = retry_count + 1,
                       last_upload_attempt = ?, last_upload_error = ?, next_attempt_at = ?
                   WHERE local_record_id = ?""",
                (now_iso(), str(error)[:500], next_attempt_at, local_record_id),
            )

    def sensor_sync_counts(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT sync_status, COUNT(*) AS c FROM sensor_records GROUP BY sync_status")
            counts = {s: 0 for s in SYNC_STATUSES}
            counts.update({r["sync_status"]: r["c"] for r in cur.fetchall()})
            return counts

    def recent_sensor_records(self, mission_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self._cursor() as cur:
            if mission_id:
                cur.execute(
                    "SELECT * FROM sensor_records WHERE mission_id = ? ORDER BY recorded_at DESC LIMIT ?",
                    (mission_id, limit),
                )
            else:
                cur.execute("SELECT * FROM sensor_records ORDER BY recorded_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
