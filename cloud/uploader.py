"""
cloud/uploader.py

Independent background worker that drains the local offline buffer to
Supabase. Fully decoupled from sensor acquisition (spec section 29) --
a cloud/network outage never blocks or slows down hardware handling.

Each cycle, for every locally-changed session:
  - ACTIVE (or any other non-COMPLETED) session: just register/refresh
    its row in Supabase (`measurement_sessions`, completed_at left
    NULL). This is never a completion marker, so it is always safe to
    push immediately.
  - COMPLETED session (i.e. MAX_READINGS_PER_GRID samples were accepted
    locally): drive it through cloud completion (see
    `_complete_session_in_cloud`) -- upload its pending samples as one
    batched JSON packet, verify against Supabase itself that every
    required sample is actually there, and ONLY THEN mark the session
    COMPLETED/cloud_synced in Supabase and delete its temporary raw
    samples from the local SQLite buffer.

CRITICAL INVARIANT (this is the bug this module fixes): a session must
never be marked COMPLETED / cloud_synced / covered in Supabase before
every one of its required raw samples is confirmed inserted there.
Local completion (all samples collected on the RPi) and cloud
completion (all samples confirmed persisted in Supabase) are two
different things, and only the latter is allowed to trigger:
  (a) marking the session completed/synced in Supabase, and
  (b) deleting the session's temporary raw samples from SQLite.
If upload or verification fails, neither (a) nor (b) happens -- the
temporary data is retained and the whole session is retried next
cycle. Retries are idempotent (keyed on (session_id, sample_number))
and unlimited by default (UPLOAD_MAX_RETRIES=0), so they can never
create duplicate `sensor_readings` rows and never lose data.

Local SQLite averages are never uploaded to Supabase -- only the raw
per-sample values, batched into one packet per session.
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
            except Exception as exc:  # noqa: BLE001 - a cloud hiccup must never crash the backend
                logger.warning("Uploader cycle error (will retry): %s", exc)
                if self._health:
                    self._health.set_cloud_reachable(False)
            self._stop_event.wait(settings.UPLOAD_POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    def _sync_sessions(self) -> None:
        if not self._supabase.available:
            return
        for session in self._db.get_unsynced_sessions():
            try:
                if session["status"] == "COMPLETED":
                    self._complete_session_in_cloud(session)
                else:
                    # Not a completion marker (completed_at stays NULL
                    # in this payload) -- just keeps Supabase's view of
                    # an in-progress session's metadata current. Always
                    # safe to push regardless of how many of its
                    # samples are uploaded yet.
                    self._supabase.upsert_session(session)
                    self._db.mark_session_synced(session["session_id"])
                    logger.info(
                        "Session %s registered/updated in cloud (status=%s, samples=%d)",
                        session["session_id"], session["status"], session["sample_count"],
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Session sync failed for %s: %s", session["session_id"], exc)

    def _complete_session_in_cloud(self, session: dict) -> None:
        """Gate for marking a session COMPLETED/cloud_synced in
        Supabase. Every step must succeed, in order, before the next
        one runs; any failure leaves the temporary SQLite data in place
        and the session unsynced, to be retried on a later cycle."""
        session_id = session["session_id"]
        required = settings.MAX_READINGS_PER_GRID

        # 1. Whatever raw samples are still in the temporary buffer for
        #    this session -- all of them, since nothing is deleted from
        #    the buffer until this entire method succeeds -- go up as
        #    ONE batched JSON packet instead of one request per sample.
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
                return  # do NOT mark completed/synced; do NOT touch the buffer

        # 2. Verify against Supabase itself -- never against local
        #    state -- exactly how many of this session's samples are
        #    actually confirmed persisted there.
        try:
            confirmed = self._supabase.count_confirmed_samples(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cloud verification failed for session %s (will retry): %s", session_id, exc,
            )
            return

        if confirmed != required:
            logger.warning(
                "Session %s not yet fully confirmed in cloud (%d/%d required) -- "
                "retaining temporary data, will retry",
                session_id, confirmed, required,
            )
            return

        # 3. ONLY now -- every required raw sample verified present in
        #    Supabase -- mark the session COMPLETED there (completed_at
        #    set). upsert_session is keyed on session_id, so this is
        #    still safe to retry.
        try:
            self._supabase.upsert_session(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Completion upsert failed for session %s (will retry): %s", session_id, exc,
            )
            return

        # 4. ONLY after that confirmed cloud completion, delete the
        #    session's temporary raw samples from SQLite and mark the
        #    session cloud_synced. This is the sole place either of
        #    those two things is allowed to happen.
        self._db.delete_session_readings(session_id)
        self._db.mark_session_synced(session_id)
        if self._health:
            self._health.set_last_successful_upload_time(time.time())
        logger.info(
            "Session %s cloud-completion confirmed (%d/%d samples) -- marked COMPLETED/"
            "cloud_synced in Supabase and purged temporary local samples",
            session_id, confirmed, required,
        )

    @staticmethod
    def _build_packet(session: dict, pending: list[dict]) -> dict:
        """Build the single batched cloud packet for a session's
        pending samples (transport format only -- Supabase still stores
        each sample as its own `sensor_readings` row; see
        SupabaseClientWrapper.upsert_readings_batch). May contain fewer
        than MAX_READINGS_PER_GRID samples if fewer are pending."""
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
