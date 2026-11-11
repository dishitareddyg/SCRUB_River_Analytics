"""
mission/manager.py

Mission lifecycle on the Raspberry Pi.  Supabase is never needed.

STATES
  PENDING            accepted payload, not yet stored
  LOADING_WAYPOINTS  writing SQLite + waypoints.json
  READY              waypoints stored & verified; acknowledgement returned
  ACTIVE             navigating (explicit start authorisation received)
  PAUSED             operator pause, navigation fault, or recovered after reboot
  COMPLETED          final GCS waypoint reached
  ABORTED            emergency stop / operator abort
  FAILED             storage failure or fatal navigation fault

LOAD (POST /api/missions):
  validate -> PENDING -> LOADING_WAYPOINTS (mission + waypoints in one
  SQLite transaction) -> atomic waypoints.json -> verify counts in both
  -> READY + waypoint_load_ack -> acknowledgement to frontend.

REBOOT RECOVERY:
  ACTIVE -> PAUSED ("recovered after restart"), motors stay at 0 until an
  operator explicitly resumes.  Half-loaded missions -> FAILED.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Callable, Optional

from config.settings import settings
from mission.store import WaypointFileStore
from mission.validator import ValidatedMission, validate_mission_payload
from monitoring.logger import get_logger
from storage.sqlite_manager import TERMINAL_STATUSES, SQLiteManager, now_iso

logger = get_logger(__name__)


class MissionError(Exception):
    """Base class; `status_code` maps to the HTTP response."""

    status_code = 400

    def __init__(self, message: str, *, errors: Optional[list] = None):
        super().__init__(message)
        self.errors = errors or [message]


class MissionNotFound(MissionError):
    status_code = 404


class MissionConflict(MissionError):
    status_code = 409


class MissionPreconditionFailed(MissionError):
    status_code = 412


class MissionStorageError(MissionError):
    status_code = 500


class MissionManager:
    def __init__(self, db: SQLiteManager, navigator, motor, gps,
                 store: Optional[WaypointFileStore] = None,
                 link_ok: Optional[Callable[[], bool]] = None,
                 on_change: Optional[Callable[[dict], None]] = None) -> None:
        self._db = db
        self._nav = navigator
        self._motor = motor
        self._gps = gps
        self._store = store or WaypointFileStore()
        self._link_ok = link_ok or (lambda: True)
        self._on_change = on_change
        self._lock = threading.RLock()

        navigator.on_waypoint_reached = self._on_waypoint_reached
        navigator.on_mission_complete = self._on_mission_complete
        navigator.on_fault = self._on_fault

    # ==================================================================
    # Load
    # ==================================================================
    def load_mission(self, raw: dict) -> dict:
        vm: ValidatedMission = validate_mission_payload(raw)  # raises MissionValidationError
        with self._lock:
            existing = self._db.get_mission(vm.mission_id)
            if existing:
                if existing["payload_hash"] == vm.payload_hash and existing["status"] != "FAILED":
                    logger.info("Mission %s re-submitted (idempotent ack)", vm.mission_id)
                    return self._ack(existing, duplicate=True)
                raise MissionConflict(
                    f"mission {vm.mission_id} already exists with status {existing['status']}"
                    + (" and a different payload" if existing["payload_hash"] != vm.payload_hash else "")
                )
            running = self.current_mission()
            if running:
                raise MissionConflict(
                    f"mission {running['mission_id']} is {running['status']}; abort or complete it first"
                )

            # PENDING -> LOADING_WAYPOINTS: mission + waypoints in one transaction.
            try:
                self._db.create_mission_with_waypoints(
                    mission_id=vm.mission_id, device_id=vm.device_id, lake_id=vm.lake_id,
                    payload_hash=vm.payload_hash, gcs=vm.gcs, polygon=vm.polygon,
                    waypoints=vm.waypoints, notes=vm.notes,
                )
            except sqlite3.IntegrityError as exc:
                raise MissionConflict(f"duplicate mission {vm.mission_id}") from exc
            except sqlite3.Error as exc:
                raise MissionStorageError(f"SQLite write failed: {exc}") from exc

            try:
                self._store.write(vm.payload)
                stored_db = self._db.count_waypoints(vm.mission_id)
                file_payload = self._store.read() or {}
                stored_file = (len(file_payload.get("waypoints", []))
                               if file_payload.get("mission_id") == vm.mission_id else -1)
                expected = len(vm.waypoints)
                if stored_db != expected or stored_file != expected:
                    raise MissionStorageError(
                        f"waypoint verification failed (expected {expected}, "
                        f"sqlite {stored_db}, json {stored_file})"
                    )
            except Exception as exc:  # noqa: BLE001
                self._db.update_mission(vm.mission_id, status="FAILED", notes=f"load failed: {exc}")
                logger.error("Mission %s load failed: %s", vm.mission_id, exc)
                if isinstance(exc, MissionError):
                    raise
                raise MissionStorageError(f"waypoint storage failed: {exc}") from exc

            self._db.update_mission(vm.mission_id, status="READY", waypoint_load_ack=1, loaded_at=now_iso())
            mission = self._db.get_mission(vm.mission_id)
        logger.info("Mission %s READY (%d waypoints stored)", vm.mission_id, len(vm.waypoints))
        self._changed(mission)
        return self._ack(mission, duplicate=False)

    @staticmethod
    def _ack(mission: dict, duplicate: bool) -> dict:
        return {
            "ok": True,
            "mission_id": mission["mission_id"],
            "status": mission["status"],
            "waypoint_load_ack": mission["waypoint_load_ack"],
            "stored_waypoints": mission["total_waypoints"],
            "payload_hash": mission["payload_hash"],
            "duplicate": duplicate,
            "loaded_at": mission["loaded_at"],
        }

    # ==================================================================
    # Commands
    # ==================================================================
    def _require(self, mission_id: str) -> dict:
        mission = self._db.get_mission(mission_id)
        if not mission:
            raise MissionNotFound(f"mission {mission_id} not found")
        return mission

    def _check_hardware(self) -> None:
        problems = []
        if settings.START_REQUIRES_STM32_LINK and not self._link_ok():
            problems.append("STM32 link is down (no packet within STM32_LINK_TIMEOUT_S)")
        if settings.START_REQUIRES_GPS_FIX:
            fix = self._gps.get_fix()
            if not fix.valid:
                problems.append("no fresh GPS fix")
            elif not fix.heading_valid:
                problems.append("no fresh compass heading")
        if problems:
            raise MissionPreconditionFailed("cannot start: " + "; ".join(problems), errors=problems)

    def start(self, mission_id: str) -> dict:
        with self._lock:
            mission = self._require(mission_id)
            if mission["status"] != "READY":
                raise MissionConflict(f"mission is {mission['status']}; only READY missions can start")
            if not mission["waypoint_load_ack"]:
                raise MissionConflict("waypoints not acknowledged as stored")
            running = self.current_mission()
            if running and running["mission_id"] != mission_id:
                raise MissionConflict(f"mission {running['mission_id']} is {running['status']}")
            waypoints = self._load_waypoints(mission)
            self._check_hardware()
            self._db.update_mission(mission_id, status="ACTIVE", started_at=now_iso(),
                                    current_waypoint_index=0, progress_percent=0.0, notes=None)
            self._nav.begin(mission_id, waypoints, start_index=0)
            self._db.set_waypoint_active(mission_id, 0)
            mission = self._db.get_mission(mission_id)
        logger.info("Mission %s ACTIVE", mission_id)
        self._changed(mission)
        return self.status(mission_id)

    def pause(self, mission_id: str, reason: str = "operator pause") -> dict:
        with self._lock:
            mission = self._require(mission_id)
            if mission["status"] != "ACTIVE":
                raise MissionConflict(f"mission is {mission['status']}; only ACTIVE missions can pause")
            self._nav.pause()
            self._db.update_mission(mission_id, status="PAUSED", notes=reason)
            mission = self._db.get_mission(mission_id)
        logger.info("Mission %s PAUSED (%s)", mission_id, reason)
        self._changed(mission)
        return self.status(mission_id)

    def resume(self, mission_id: str) -> dict:
        with self._lock:
            mission = self._require(mission_id)
            if mission["status"] != "PAUSED":
                raise MissionConflict(f"mission is {mission['status']}; only PAUSED missions can resume")
            waypoints = self._load_waypoints(mission)
            self._check_hardware()
            idx = int(mission["current_waypoint_index"])
            elapsed = self._nav.runtime_s() if self._nav.mission_id == mission_id else 0.0
            self._db.update_mission(mission_id, status="ACTIVE", notes=None)
            self._nav.begin(mission_id, waypoints, start_index=idx, elapsed_runtime_s=elapsed)
            self._db.set_waypoint_active(mission_id, idx)
            mission = self._db.get_mission(mission_id)
        logger.info("Mission %s RESUMED at waypoint %d", mission_id, idx)
        self._changed(mission)
        return self.status(mission_id)

    def abort(self, mission_id: Optional[str] = None, reason: str = "emergency stop") -> dict:
        """
        Emergency stop.  Motors are zeroed FIRST (direct UART write, no
        network needed), then mission state is updated.
        """
        self._motor.emergency_stop()
        with self._lock:
            if mission_id is None:
                current = self.current_mission()
                mission_id = current["mission_id"] if current else None
            if self._nav.mission_id in (None, mission_id):
                self._nav.clear()
            if mission_id is None:
                logger.warning("Emergency stop with no active mission — motors zeroed")
                return {"ok": True, "mission_id": None, "status": None, "motors": "STOPPED"}
            mission = self._require(mission_id)
            if mission["status"] in TERMINAL_STATUSES:
                return {**self.status(mission_id), "motors": "STOPPED"}
            self._db.update_mission(mission_id, status="ABORTED", completed_at=now_iso(), notes=reason)
            mission = self._db.get_mission(mission_id)
        logger.warning("Mission %s ABORTED (%s)", mission_id, reason)
        self._changed(mission)
        return {**self.status(mission_id), "motors": "STOPPED"}

    # ==================================================================
    # Queries
    # ==================================================================
    def current_mission(self) -> Optional[dict]:
        rows = self._db.list_missions(statuses=("ACTIVE", "PAUSED"), limit=1)
        return rows[0] if rows else None

    def current_mission_id(self) -> Optional[str]:
        m = self.current_mission()
        return m["mission_id"] if m else None

    def status(self, mission_id: str) -> dict:
        mission = self._require(mission_id)
        nav = self._nav.status() if self._nav.mission_id == mission_id else {}
        total = mission["total_waypoints"]
        idx = mission["current_waypoint_index"]
        returning = (mission["status"] in ("ACTIVE", "PAUSED") and total > 0 and idx == total - 1)
        return {
            "mission_id": mission["mission_id"],
            "device_id": mission["device_id"],
            "lake_id": mission["lake_id"],
            "status": mission["status"],
            "waypoint_load_ack": mission["waypoint_load_ack"],
            "total_waypoints": total,
            "current_waypoint_index": idx,
            "completed_waypoints": min(idx, total) if mission["status"] != "COMPLETED" else total,
            "progress_percent": mission["progress_percent"],
            "returning_to_gcs": returning,
            "ground_control": {"latitude": mission["gcs_latitude"], "longitude": mission["gcs_longitude"]},
            "created_at": mission["created_at"],
            "loaded_at": mission["loaded_at"],
            "started_at": mission["started_at"],
            "completed_at": mission["completed_at"],
            "notes": mission["notes"],
            "cloud_synced": mission["cloud_synced_version"] >= mission["cloud_version"],
            "navigation": nav or None,
        }

    def _load_waypoints(self, mission: dict) -> list[dict]:
        wps = self._db.get_waypoints(mission["mission_id"])
        if len(wps) != mission["total_waypoints"] or not wps:
            raise MissionStorageError(
                f"stored waypoints incomplete ({len(wps)}/{mission['total_waypoints']})"
            )
        return wps

    # ==================================================================
    # Reboot recovery
    # ==================================================================
    def recover_after_restart(self) -> list[str]:
        """Never restarts motion: ACTIVE missions become PAUSED."""
        notes = []
        with self._lock:
            for m in self._db.list_missions(statuses=("PENDING", "LOADING_WAYPOINTS"), limit=100):
                self._db.update_mission(m["mission_id"], status="FAILED",
                                        notes="incomplete waypoint load interrupted by restart")
                notes.append(f"{m['mission_id']}: incomplete load -> FAILED")
            for m in self._db.list_missions(statuses=("ACTIVE", "PAUSED", "READY"), limit=100):
                count = self._db.count_waypoints(m["mission_id"])
                if count != m["total_waypoints"]:
                    self._db.update_mission(m["mission_id"], status="FAILED",
                                            notes=f"waypoints missing after restart ({count}/{m['total_waypoints']})")
                    notes.append(f"{m['mission_id']}: waypoints missing -> FAILED")
                elif m["status"] == "ACTIVE":
                    self._db.update_mission(
                        m["mission_id"], status="PAUSED",
                        notes="recovered after restart — operator must resume",
                    )
                    notes.append(f"{m['mission_id']}: ACTIVE -> PAUSED (awaiting operator)")
        self._motor.set_zero()
        for n in notes:
            logger.warning("Recovery: %s", n)
        return notes

    # ==================================================================
    # Navigator callbacks (run in the navigator thread, outside its lock)
    # ==================================================================
    def _on_waypoint_reached(self, mission_id: str, seq: int, next_index: int, total: int) -> None:
        progress = round(100.0 * min(next_index, total) / total, 2) if total else 0.0
        self._db.record_waypoint_reached(mission_id, seq, min(next_index, total - 1), progress)
        self._changed(self._db.get_mission(mission_id))

    def _on_mission_complete(self, mission_id: str) -> None:
        with self._lock:
            self._db.update_mission(mission_id, status="COMPLETED", completed_at=now_iso(),
                                    progress_percent=100.0)
            mission = self._db.get_mission(mission_id)
        logger.info("Mission %s COMPLETED", mission_id)
        self._changed(mission)

    def _on_fault(self, mission_id: str, reason: str, fatal: bool) -> None:
        with self._lock:
            mission = self._db.get_mission(mission_id)
            if not mission or mission["status"] != "ACTIVE":
                return
            if fatal:
                self._db.update_mission(mission_id, status="FAILED", completed_at=now_iso(),
                                        notes=f"navigation fault: {reason}")
                self._nav.clear()
            else:
                self._db.update_mission(mission_id, status="PAUSED",
                                        notes=f"auto-paused: {reason} — operator must resume")
            mission = self._db.get_mission(mission_id)
        self._changed(mission)

    def _changed(self, mission: Optional[dict]) -> None:
        if mission and self._on_change:
            try:
                self._on_change(mission)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mission on_change callback failed: %s", exc)
