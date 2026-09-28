"""
cloud/uploader.py

Background cloud uploader worker for autonomous navigation bot.
Drains local offline buffer to Supabase.
Preserves the critical invariant:
  A session is NEVER marked completed or cleared from local SQLite until
  every required sample is verified present in Supabase directly!
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from cloud.supabase_client import SupabaseClientWrapper
from config.settings import settings
from monitoring.logger import get_logger
from storage.buffer_manager import BufferManager
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class UploaderWorker:
    def __init__(self, sqlite_manager: SQLiteManager, supabase_client: SupabaseClientWrapper, health=None):
        self._db = sqlite_manager
        self._buffer = BufferManager(sqlite_manager)
        self._supabase = supabase_client
        self._health = health
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="UploaderWorker", daemon=True)
        self._thread.start()
        logger.info("Cloud uploader worker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._sync_sessions()
                if self._health:
                    self._health.set_pending_upload_count(self._buffer.pending_count())
                    self._health.set_cloud_reachable(self._supabase.available)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Uploader cycle error (will retry): %s", exc)
                if self._health:
                    self._health.set_cloud_reachable(False)
            self._stop_event.wait(settings.UPLOAD_POLL_INTERVAL_SECONDS)

    def _sync_sessions(self) -> None:
        if not self._supabase.available:
            return
        for session in self._db.get_unsynced_sessions():
            try:
                if session["status"] == "COMPLETED":
                    self._complete_session_in_cloud(session)
                else:
                    self._supabase.upsert_session(session)
                    self._db.mark_session_synced(session["session_id"])
                    logger.info(
                        "Session %s registered in cloud (status=%s, samples=%d)",
                        session["session_id"], session["status"], session["sample_count"],
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Session sync failed for %s: %s", session["session_id"], exc)

    def _complete_session_in_cloud(self, session: dict) -> None:
        session_id = session["session_id"]
        required = settings.MAX_READINGS_PER_GRID

        # 1. Batch upload pending samples
        pending = self._db.get_readings_for_session(session_id)
        if pending:
            packet = self._build_packet(session, pending)
            try:
                self._supabase.upsert_readings_batch(packet)
                logger.info(
                    "Batch upload sent for session %s: %d sample(s)",
                    session_id, len(pending),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Batch upload failed for session %s (samples retained, will retry): %s",
                    session_id, exc,
                )
                return

        # 2. Verify against Supabase ground truth
        try:
            confirmed = self._supabase.count_confirmed_samples(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cloud verification failed for session %s (will retry): %s", session_id, exc,
            )
            return

        if confirmed != required:
            logger.warning(
                "Session %s not yet fully confirmed in cloud (%d/%d required) — retaining buffer",
                session_id, confirmed, required,
            )
            return

        # 3. Mark session COMPLETED in Supabase
        try:
            self._supabase.upsert_session(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Completion upsert failed for %s (will retry): %s", session_id, exc)
            return

        # 4. Purge local temporary buffer and mark synced
        self._db.delete_session_readings(session_id)
        self._db.mark_session_synced(session_id)
        if self._health:
            self._health.set_last_successful_upload_time(time.time())
        logger.info(
            "Session %s cloud-completion confirmed (%d/%d samples) — purged local buffer",
            session_id, confirmed, required,
        )

    @staticmethod
    def _build_packet(session: dict, pending: list[dict]) -> dict:
        return {
            "session_id": session["session_id"],
            "grid_id": session["grid_id"],
            "device_id": session["device_id"],
            "samples": [
                {
                    "reading_id": item["reading_id"],
                    "sample_number": item["sample_number"],
                    "recorded_at": item["recorded_at"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "ph": item["ph"],
                    "tds": item["tds"],
                    "turbidity": item["turbidity"],
                    "temperature_c": item["temperature_c"],
                    "humidity_percent": item["humidity_percent"],
                }
                for item in pending
            ],
        }
