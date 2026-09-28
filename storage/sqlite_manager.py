"""
storage/sqlite_manager.py

Lightweight local SQLite persistence for the Autonomous Navigation bot.
Manages:
  1. Offline buffering of accepted readings awaiting cloud upload (local_readings).
     Kept in SQLite until cloud confirmation, then deleted.
  2. Local session state (local_sessions) with atomic running sum/count aggregation.
  3. Local final averages (local_averages) for completed sessions.
  4. Cached grid definitions synced from Supabase (grid_cache).

Uses SQLite WAL mode for concurrency and crash-resilience.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Iterable, Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_sessions (
    session_id      TEXT PRIMARY KEY,
    grid_id         TEXT NOT NULL,
    grid_code       TEXT,
    device_id       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE','COMPLETED','ABANDONED')) DEFAULT 'ACTIVE',
    sample_count    INTEGER NOT NULL DEFAULT 0,
    latitude        REAL,
    longitude       REAL,
    cloud_synced    INTEGER NOT NULL DEFAULT 0,
    sum_ph                  REAL NOT NULL DEFAULT 0,
    count_ph                INTEGER NOT NULL DEFAULT 0,
    sum_tds                 REAL NOT NULL DEFAULT 0,
    count_tds               INTEGER NOT NULL DEFAULT 0,
    sum_turbidity            REAL NOT NULL DEFAULT 0,
    count_turbidity          INTEGER NOT NULL DEFAULT 0,
    sum_temperature_c        REAL NOT NULL DEFAULT 0,
    count_temperature_c      INTEGER NOT NULL DEFAULT 0,
    sum_humidity_percent     REAL NOT NULL DEFAULT 0,
    count_humidity_percent   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_local_sessions_grid_status
    ON local_sessions(grid_id, status);

CREATE TABLE IF NOT EXISTS local_readings (
    reading_id          TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    grid_id             TEXT NOT NULL,
    device_id           TEXT NOT NULL,
    sample_number       INTEGER NOT NULL,
    recorded_at         TEXT NOT NULL,
    latitude            REAL,
    longitude           REAL,
    ph                  REAL,
    tds                 REAL,
    turbidity           REAL,
    temperature_c       REAL,
    humidity_percent    REAL,
    created_at          TEXT NOT NULL,
    upload_status       TEXT NOT NULL CHECK (upload_status IN ('PENDING','FAILED')) DEFAULT 'PENDING',
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_attempt_at     TEXT,
    last_error          TEXT,
    UNIQUE(session_id, sample_number)
);

CREATE INDEX IF NOT EXISTS idx_local_readings_status ON local_readings(upload_status);

CREATE TABLE IF NOT EXISTS local_averages (
    grid_id                 TEXT NOT NULL,
    session_id              TEXT NOT NULL,
    avg_ph                  REAL,
    avg_tds                 REAL,
    avg_turbidity           REAL,
    avg_temperature_c       REAL,
    avg_humidity_percent    REAL,
    sample_count            INTEGER NOT NULL,
    calculated_at           TEXT NOT NULL,
    PRIMARY KEY (grid_id, session_id)
);

CREATE TABLE IF NOT EXISTS grid_cache (
    grid_id         TEXT PRIMARY KEY,
    lake_id         TEXT,
    grid_code       TEXT,
    grid_size_m     REAL,
    center_lat      REAL NOT NULL,
    center_lon      REAL NOT NULL,
    synced_at       TEXT NOT NULL
);
"""

_AGG_FIELDS = [
    ("ph", "sum_ph", "count_ph"),
    ("tds", "sum_tds", "count_tds"),
    ("turbidity", "sum_turbidity", "count_turbidity"),
    ("temperature_c", "sum_temperature_c", "count_temperature_c"),
    ("humidity_percent", "sum_humidity_percent", "count_humidity_percent"),
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class SQLiteManager:
    def __init__(self, path: Optional[str] = None):
        self._path = path or settings.SQLITE_PATH
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=OFF;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        logger.info("SQLite schema initialized at %s", self._path)

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

    # ------------------------------------------------------------------
    # Grid cache
    # ------------------------------------------------------------------
    def replace_grid_cache(self, grids: Iterable[dict]) -> None:
        grids = list(grids)
        with self._cursor() as cur:
            cur.execute("DELETE FROM grid_cache")
            now = _now_iso()
            cur.executemany(
                """INSERT INTO grid_cache
                   (grid_id, lake_id, grid_code, grid_size_m, center_lat, center_lon, synced_at)
                   VALUES (:grid_id, :lake_id, :grid_code, :grid_size_m, :center_lat, :center_lon, :synced_at)""",
                [{**g, "synced_at": now} for g in grids],
            )
        logger.info("Grid cache refreshed with %d grids", len(grids))

    def get_cached_grids(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM grid_cache")
            return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def get_active_session(self, grid_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT * FROM local_sessions
                   WHERE grid_id = ? AND status = 'ACTIVE'
                   ORDER BY started_at DESC LIMIT 1""",
                (grid_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def create_session(self, grid_id: str, grid_code: str, device_id: str,
                       latitude: float, longitude: float) -> dict:
        session_id = str(uuid.uuid4())
        started_at = _now_iso()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO local_sessions
                   (session_id, grid_id, grid_code, device_id, started_at, status,
                    sample_count, latitude, longitude, cloud_synced)
                   VALUES (?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, 0)""",
                (session_id, grid_id, grid_code, device_id, started_at, latitude, longitude),
            )
        logger.info("Created local session %s for grid %s", session_id, grid_code)
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM local_sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_unsynced_sessions(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM local_sessions WHERE cloud_synced = 0")
            return [dict(row) for row in cur.fetchall()]

    def mark_session_synced(self, session_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE local_sessions SET cloud_synced = 1 WHERE session_id = ?", (session_id,))

    # ------------------------------------------------------------------
    # Accepted-sample atomic pipeline
    # ------------------------------------------------------------------
    def record_accepted_sample(self, *, session_id: str, grid_id: str, device_id: str,
                                recorded_at: str, latitude: Optional[float], longitude: Optional[float],
                                ph: Optional[float], tds: Optional[float],
                                turbidity: Optional[float], temperature_c: Optional[float],
                                humidity_percent: Optional[float], max_readings: int) -> dict:
        reading_id = str(uuid.uuid4())
        created_at = _now_iso()
        values = {
            "ph": ph, "tds": tds, "turbidity": turbidity,
            "temperature_c": temperature_c, "humidity_percent": humidity_percent,
        }

        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM local_sessions WHERE session_id = ?", (session_id,)
            )
            session_row = cur.fetchone()
            if session_row is None:
                raise ValueError(f"Unknown session_id {session_id!r}")
            session = dict(session_row)
            if session["status"] != "ACTIVE":
                raise ValueError(f"Session {session_id!r} is not ACTIVE (status={session['status']!r})")
            sample_number = session["sample_count"] + 1

            cur.execute(
                """INSERT INTO local_readings
                   (reading_id, session_id, grid_id, device_id, sample_number, recorded_at,
                    latitude, longitude, ph, tds, turbidity, temperature_c,
                    humidity_percent, created_at, upload_status, retry_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0)""",
                (reading_id, session_id, grid_id, device_id, sample_number, recorded_at,
                 latitude, longitude, ph, tds, turbidity, temperature_c,
                 humidity_percent, created_at),
            )

            set_clauses = ["sample_count = sample_count + 1", "cloud_synced = 0"]
            params: list = []
            for field_name, sum_col, count_col in _AGG_FIELDS:
                value = values[field_name]
                set_clauses.append(f"{sum_col} = {sum_col} + ?")
                set_clauses.append(f"{count_col} = {count_col} + ?")
                params.append(value if value is not None else 0)
                params.append(1 if value is not None else 0)
            params.append(session_id)
            cur.execute(
                f"UPDATE local_sessions SET {', '.join(set_clauses)} WHERE session_id = ?",
                params,
            )

            cur.execute("SELECT * FROM local_sessions WHERE session_id = ?", (session_id,))
            session = dict(cur.fetchone())

            averages: Optional[dict] = None
            if session["sample_count"] >= max_readings and session["status"] == "ACTIVE":
                completed_at = _now_iso()
                averages = {
                    field_name: (session[sum_col] / session[count_col]) if session[count_col] else None
                    for field_name, sum_col, count_col in _AGG_FIELDS
                }
                cur.execute(
                    "UPDATE local_sessions SET status = 'COMPLETED', completed_at = ?, cloud_synced = 0 "
                    "WHERE session_id = ?",
                    (completed_at, session_id),
                )
                cur.execute(
                    """INSERT INTO local_averages
                       (grid_id, session_id, avg_ph, avg_tds, avg_turbidity,
                        avg_temperature_c, avg_humidity_percent, sample_count, calculated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(grid_id, session_id) DO UPDATE SET
                         avg_ph=excluded.avg_ph, avg_tds=excluded.avg_tds,
                         avg_turbidity=excluded.avg_turbidity,
                         avg_temperature_c=excluded.avg_temperature_c,
                         avg_humidity_percent=excluded.avg_humidity_percent,
                         sample_count=excluded.sample_count,
                         calculated_at=excluded.calculated_at""",
                    (grid_id, session_id, averages["ph"], averages["tds"],
                     averages["turbidity"], averages["temperature_c"],
                     averages["humidity_percent"], session["sample_count"], completed_at),
                )
                session["status"] = "COMPLETED"
                session["completed_at"] = completed_at

        return {
            "session": session,
            "sample_number": sample_number,
            "reading_id": reading_id,
            "averages": averages,
        }

    def get_pending_uploads(self, limit: int) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM local_readings WHERE upload_status IN ('PENDING','FAILED') "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_upload_succeeded(self, reading_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM local_readings WHERE reading_id = ?", (reading_id,))

    def mark_upload_failed(self, reading_id: str, error: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """UPDATE local_readings
                   SET upload_status='FAILED', retry_count = retry_count + 1,
                       last_attempt_at = ?, last_error = ?
                   WHERE reading_id = ?""",
                (_now_iso(), str(error)[:500], reading_id),
            )

    def count_pending_uploads(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM local_readings WHERE upload_status IN ('PENDING','FAILED')")
            return cur.fetchone()["c"]

    def get_readings_for_session(self, session_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM local_readings WHERE session_id = ? ORDER BY sample_number ASC",
                (session_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def delete_session_readings(self, session_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM local_readings WHERE session_id = ?", (session_id,))

    def get_local_average(self, grid_id: str, session_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM local_averages WHERE grid_id = ? AND session_id = ?",
                (grid_id, session_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
