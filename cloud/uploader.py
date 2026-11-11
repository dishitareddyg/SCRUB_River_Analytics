"""
cloud/uploader.py

Offline-first cloud synchronisation.  Both workers run in their own
threads and never block UART, navigation, motors or telemetry.

SensorUploader (rate limited)
  * at most ONE sensor record per UPLOAD_INTERVAL_S (default 10 s),
    measured start-to-start; never concurrent, never a burst
  * oldest record first (recorded_at), PENDING or FAILED with elapsed back-off
  * connectivity probe before each attempt; offline -> record untouched
  * idempotent upsert on local_record_id; SYNCED only after confirmation
  * failure -> FAILED, retry_count+1, exponential back-off; never deleted
  * records whose mission is not yet in the cloud wait for MissionSync

MissionSyncWorker
  * pushes mission metadata/status/progress whenever the local
    cloud_version advances, the waypoint list once, then every
    waypoint status change (PENDING -> ACTIVE -> COMPLETED / SKIPPED)
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from cloud.supabase_client import SupabaseClientWrapper
from config.settings import settings
from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


def retry_delay_s(retry_count: int) -> float:
    """Exponential back-off: base * 2^n capped at UPLOAD_RETRY_MAX_S."""
    return min(settings.UPLOAD_RETRY_BASE_S * (2 ** max(0, retry_count)), settings.UPLOAD_RETRY_MAX_S)


class SensorUploader:
    def __init__(self, db: SQLiteManager, supabase: SupabaseClientWrapper, health=None,
                 clock=time.monotonic) -> None:
        self._db = db
        self._supabase = supabase
        self._health = health
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_attempt: Optional[float] = None
        self.attempts = 0
        self.successes = 0
        self.online: Optional[bool] = None

    @property
    def interval(self) -> float:
        # Hard floor: the documented contract is max ONE record / 10 s.
        return max(10.0, settings.UPLOAD_INTERVAL_S)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="SensorUploader", daemon=True)
        self._thread.start()
        logger.info("Sensor uploader started (max 1 record / %.0fs)", self.interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=settings.SUPABASE_TIMEOUT_S + 2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            result = None
            try:
                result = self.run_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Uploader cycle error: %s", exc)
            wait = self.seconds_until_next_slot()
            if result in ("idle", "disabled", None):
                wait = max(wait, 2.0)  # nothing queued: cheap local poll
            self._stop_event.wait(wait)

    def seconds_until_next_slot(self) -> float:
        if self._last_attempt is None:
            return 0.0
        return max(0.0, self._last_attempt + self.interval - self._clock())

    def run_once(self) -> Optional[str]:
        """
        Try to upload ONE record if the rate-limit slot is open.
        Returns "synced", "failed", "offline", "idle", "disabled" or "rate_limited".
        """
        if not self._supabase.available:
            self._report(False)
            return "disabled"
        if self.seconds_until_next_slot() > 0:
            return "rate_limited"
        record = self._db.next_record_to_upload()
        if record is None:
            self._update_pending()
            return "idle"
        # The connectivity probe consumes the slot too, so an offline bot
        # does not hammer the network.
        self._last_attempt = self._clock()
        if not self._supabase.is_reachable():
            self._report(False)
            return "offline"
        self.attempts += 1
        try:
            self._supabase.upsert_sensor_reading(record)
        except Exception as exc:  # noqa: BLE001 - network, HTTP, RLS, timeout
            delay = retry_delay_s(record["retry_count"])
            self._db.mark_record_failed(record["local_record_id"], str(exc), time.time() + delay)
            logger.warning("Upload of %s failed (retry in %.0fs): %s", record["local_record_id"], delay, exc)
            self._report(False)
            self._update_pending()
            return "failed"
        self._db.mark_record_synced(record["local_record_id"])
        self.successes += 1
        self._report(True)
        self._update_pending()
        if self._health:
            self._health.set_last_successful_upload_time(time.time())
        logger.info("Sensor record %s SYNCED", record["local_record_id"])
        return "synced"

    def _report(self, online: bool) -> None:
        self.online = online
        if self._health:
            self._health.set_cloud_reachable(online)

    def _update_pending(self) -> None:
        if self._health:
            c = self._db.sensor_sync_counts()
            self._health.set_pending_upload_count(c["PENDING"] + c["FAILED"])


class MissionSyncWorker:
    def __init__(self, db: SQLiteManager, supabase: SupabaseClientWrapper, health=None) -> None:
        self._db = db
        self._supabase = supabase
        self._health = health
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MissionSync", daemon=True)
        self._thread.start()
        logger.info("Mission sync worker started (interval=%.0fs)", settings.MISSION_SYNC_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=settings.SUPABASE_TIMEOUT_S + 2)

    def notify(self, _mission: Optional[dict] = None) -> None:
        """Wake early after a local mission change (non-blocking)."""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Mission sync cycle error: %s", exc)
            self._wake.wait(settings.MISSION_SYNC_INTERVAL_S)
            self._wake.clear()

    def run_once(self) -> int:
        if not self._supabase.available:
            return 0
        pending = self._db.missions_needing_sync()
        if not pending or not self._supabase.is_reachable():
            return 0
        synced = 0
        for mission in pending:
            version = mission["cloud_version"]
            try:
                self._supabase.upsert_mission(mission)
                # Full list once, afterwards only waypoints whose status changed.
                waypoints = (self._db.get_waypoints(mission["mission_id"])
                             if not mission["waypoints_cloud_synced"]
                             else self._db.dirty_waypoints(mission["mission_id"]))
                if waypoints:
                    self._supabase.upsert_waypoints(mission["mission_id"], waypoints)
                self._db.mark_waypoints_synced(mission["mission_id"], waypoints)
                self._db.mark_mission_synced(mission["mission_id"], version)
                synced += 1
                logger.info("Mission %s synced to cloud (status=%s, v%d)",
                            mission["mission_id"], mission["status"], version)
            except Exception as exc:  # noqa: BLE001
                self._db.mark_mission_sync_error(mission["mission_id"], str(exc))
                logger.warning("Mission %s cloud sync failed (will retry): %s", mission["mission_id"], exc)
        return synced
