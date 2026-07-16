"""Serial-to-database ingestion worker.

Bridges Module 2 (serial acquisition) to this module (the database
layer) without requiring any changes to
:mod:`app.serial.serial_manager`: :class:`IngestionWorker` simply
pulls validated packets off a
:class:`~app.serial.queue_manager.PacketQueue` (the same queue
``SerialManager`` already writes into) on its own background thread
and hands each one to :class:`~app.database.service.DatabaseService`.

This mirrors ``SerialManager``'s own threading model (a daemon thread,
a ``threading.Event`` for graceful shutdown, no busy-waiting) so the
two components compose naturally, e.g.::

    from app.serial.serial_manager import SerialManager
    from app.database.service import get_database_service
    from app.database.ingestion_worker import IngestionWorker

    serial_manager = SerialManager()
    serial_manager.start()

    ingestion_worker = IngestionWorker(
        queue=serial_manager.queue, database_service=get_database_service()
    )
    ingestion_worker.start()

Wiring this into the application's startup/shutdown lifecycle
(``app/main.py``) is left to a future integration step, per this
module's scope (database layer only).
"""

from __future__ import annotations

import threading
from typing import Optional

from app.database.service import DatabaseService
from app.serial.queue_manager import PacketQueue
from app.utils.exceptions import ApplicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_POLL_TIMEOUT_SECONDS = 1.0


class IngestionWorker:
    """Consumes validated packets from a queue and persists them.

    Attributes:
        stored_count: Total number of packets successfully persisted
            since this worker started.
        error_count: Total number of packets that failed to persist.
    """

    def __init__(
        self,
        queue: PacketQueue,
        database_service: DatabaseService,
        poll_timeout_seconds: float = _DEFAULT_POLL_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the worker.

        Args:
            queue: The packet queue to consume from (typically
                ``SerialManager.queue``).
            database_service: The service used to persist packets.
            poll_timeout_seconds: How long each blocking
                ``queue.get()`` call waits before checking the stop
                condition again - keeps shutdown responsive without
                busy-waiting.
        """
        self._queue = queue
        self._db = database_service
        self._poll_timeout_seconds = poll_timeout_seconds

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.stored_count = 0
        self.error_count = 0

    def start(self) -> None:
        """Start the background ingestion thread.

        Safe to call at most once per instance. If already started,
        logs a warning and returns without creating a second thread.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("IngestionWorker.start() called while already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="database-ingestion",
            daemon=True,
        )
        self._thread.start()
        logger.info("Database ingestion worker started.")

    def stop(self, join_timeout_seconds: float = 5.0) -> None:
        """Signal the background thread to stop and wait for it to exit.

        Args:
            join_timeout_seconds: Maximum time to wait for the
                ingestion thread to exit cleanly.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_seconds)
            if self._thread.is_alive():  # pragma: no cover - defensive
                logger.warning("Ingestion worker thread did not stop within timeout.")
            else:
                logger.info("Database ingestion worker stopped.")

    def _run(self) -> None:
        """Main consume loop, executed on the background thread.

        Never raises out of the thread: persistence failures for a
        single packet are caught, logged, and counted, so one bad
        packet can never crash the ingestion thread or block the
        serial acquisition thread producing into the same queue.
        """
        while not self._stop_event.is_set():
            packet = self._queue.get(timeout=self._poll_timeout_seconds)
            if packet is None:
                continue  # Poll timeout with nothing queued; loop and re-check stop condition.

            try:
                self._db.save_sensor_packet(packet)
                self.stored_count += 1
            except ApplicationError as exc:
                self.error_count += 1
                logger.error(
                    f"Failed to persist packet (device={packet.device_id}, "
                    f"sequence={packet.sequence}): {exc.message}"
                )
            except Exception as exc:  # pragma: no cover - defensive catch-all
                self.error_count += 1
                logger.exception(
                    f"Unexpected error persisting packet (device={packet.device_id}, "
                    f"sequence={packet.sequence}): {exc}"
                )
