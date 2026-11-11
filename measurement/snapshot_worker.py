"""
measurement/snapshot_worker.py

Persists ONE GPS-tagged sensor snapshot every SENSOR_STORE_INTERVAL_S
(default 10 s) even though the STM32 delivers a packet every 2 s.

Each snapshot:
  * latest sensor readings (out-of-range / missing values kept as NULL)
  * latest GPS fix + compass heading; if the fix is stale or missing the
    coordinates are stored as NULL with gps_valid = 0 and gps_age_seconds
    so stale positions are never silently attached to a reading
  * mission_id of the ACTIVE / PAUSED mission (NULL otherwise)
  * device_id, recorded_at (RPi UTC), hardware_timestamp (STM32 timestamp)
  * new local_record_id UUID, sync_status = PENDING

Snapshots are skipped only when no STM32 packet arrived recently
(SENSOR_MAX_AGE_S) — i.e. there is no fresh hardware data at all.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from typing import Callable, Optional

from config.settings import settings
from hardware.gps import GPSWorker
from hardware.live_state import LiveState
from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager, now_iso

logger = get_logger(__name__)


class SensorSnapshotWorker:
    def __init__(self, db: SQLiteManager, live_state: LiveState, gps: GPSWorker,
                 mission_id_provider: Callable[[], Optional[str]], health=None) -> None:
        self._db = db
        self._live = live_state
        self._gps = gps
        self._mission_id = mission_id_provider
        self._health = health
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.records_written = 0
        self.last_record_id: Optional[str] = None
        self._skip_logged = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="SensorSnapshot", daemon=True)
        self._thread.start()
        logger.info("Sensor snapshot worker started (interval=%.1fs)", settings.SENSOR_STORE_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = max(1.0, settings.SENSOR_STORE_INTERVAL_S)
        next_due = time.monotonic() + interval
        while not self._stop_event.wait(max(0.0, next_due - time.monotonic())):
            next_due += interval
            if next_due < time.monotonic():  # overrun: realign instead of bursting
                next_due = time.monotonic() + interval
            try:
                self.capture_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Sensor snapshot failed: %s", exc)
                if self._health:
                    self._health.set_sqlite_ok(False)

    def capture_once(self) -> Optional[dict]:
        """Capture and persist one snapshot. Returns the record or None if skipped."""
        state = self._live.snapshot()
        if state.received_at is None or time.time() - state.received_at > settings.SENSOR_MAX_AGE_S:
            if not self._skip_logged:
                logger.warning("No fresh STM32 packet — sensor snapshot skipped")
                self._skip_logged = True
            return None
        self._skip_logged = False

        fix = self._gps.get_fix()
        gps_age = None if math.isinf(fix.age_seconds) else round(fix.age_seconds, 2)
        record = {
            "local_record_id": str(uuid.uuid4()),
            "mission_id": self._mission_id(),
            "device_id": state.device_id or settings.DEVICE_ID,
            "recorded_at": now_iso(),
            "hardware_timestamp": state.hardware_timestamp,
            "latitude": fix.latitude if fix.valid else None,
            "longitude": fix.longitude if fix.valid else None,
            "heading": fix.heading if fix.heading_valid else None,
            "gps_valid": 1 if fix.valid else 0,
            "gps_age_seconds": gps_age,
            **state.readings,
        }
        if not fix.valid:
            logger.warning("Sensor snapshot stored without location (gps age=%s s)", gps_age)
        self._db.insert_sensor_record(record)
        self.records_written += 1
        self.last_record_id = record["local_record_id"]
        if self._health:
            self._health.set_sqlite_ok(True)
        logger.debug("Sensor snapshot %s stored", record["local_record_id"])
        return record
