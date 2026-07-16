"""Serial acquisition manager.

The top-level orchestrator for the serial acquisition subsystem. Owns
a background worker thread that:

    1. Opens (or auto-detects and opens) the configured serial port.
    2. Continuously reads lines via :class:`SerialReader`.
    3. Parses each line via :class:`PacketParser`.
    4. Validates each parsed packet via :class:`PacketValidator`.
    5. Pushes valid packets onto a :class:`PacketQueue` for downstream
       modules to consume.
    6. Updates :class:`DeviceManager` and :class:`StatusManager` so
       the rest of the backend can observe acquisition health.
    7. Automatically reconnects (with backoff) on any communication
       failure - cable removal, Arduino reset, or read errors.

This module never writes to a database, performs analytics, or runs
machine learning; it is solely responsible for reliable data
acquisition, as required by this module's scope.
"""

from __future__ import annotations

import threading
from typing import Optional

from app.config.settings import Settings, get_settings
from app.serial.device_manager import DeviceManager
from app.serial.packet_parser import PacketParser
from app.serial.packet_validator import PacketValidator
from app.serial.queue_manager import PacketQueue
from app.serial.sensor_registry import SensorRegistry, get_sensor_registry
from app.serial.serial_reader import SerialReader
from app.serial.status import ConnectionStatus, StatusManager
from app.utils.exceptions import CommunicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SerialManager:
    """Coordinates serial acquisition on a dedicated background thread.

    Instances are safe to :meth:`start` once and :meth:`stop` once;
    they are not designed to be restarted after stopping. A future
    revision of ``app/main.py`` is expected to call :meth:`start` on
    application startup and :meth:`stop` on shutdown so the
    acquisition loop never blocks request handling.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        registry: Optional[SensorRegistry] = None,
    ) -> None:
        """Initialize the manager and its collaborators.

        Args:
            settings: Application settings. Defaults to
                :func:`app.config.settings.get_settings`.
            registry: Sensor registry. Defaults to
                :func:`app.serial.sensor_registry.get_sensor_registry`.
        """
        self._settings = settings or get_settings()
        self._registry = registry or get_sensor_registry()

        self._reader = SerialReader(
            baud_rate=self._settings.serial_baud_rate,
            connect_timeout_seconds=self._settings.serial_connect_timeout_seconds,
            read_timeout_seconds=self._settings.serial_read_timeout_seconds,
            max_line_bytes=self._settings.serial_max_line_bytes,
        )
        self._parser = PacketParser()
        self._validator = PacketValidator(self._registry)
        self.queue = PacketQueue(max_size=self._settings.serial_queue_max_size)
        self.devices = DeviceManager()
        self.status = StatusManager()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background acquisition thread.

        Safe to call at most once per instance. If already started,
        logs a warning and returns without creating a second thread.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("SerialManager.start() called while already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="serial-acquisition",
            daemon=True,
        )
        self._thread.start()
        logger.info("Serial acquisition thread started.")

    def stop(self, join_timeout_seconds: float = 5.0) -> None:
        """Signal the background thread to stop and wait for it to exit.

        Args:
            join_timeout_seconds: Maximum time to wait for the
                acquisition thread to exit cleanly.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_seconds)
            if self._thread.is_alive():  # pragma: no cover - defensive
                logger.warning("Serial acquisition thread did not stop within timeout.")
            else:
                logger.info("Serial acquisition thread stopped.")
        self._reader.close()
        self.devices.mark_disconnected()
        self.status.set_status(ConnectionStatus.DISCONNECTED)

    def _resolve_port(self) -> Optional[str]:
        """Determine which serial port to connect to.

        Returns:
            The port identifier to use, or ``None`` if auto-detection
            was requested but no candidate port was found.
        """
        configured_port = self._settings.serial_com_port
        if self._settings.serial_auto_detect and (
            not configured_port or configured_port.lower() == "auto"
        ):
            return SerialReader.detect_port()
        return configured_port

    def _run(self) -> None:
        """Main acquisition loop, executed on the background thread.

        Never raises out of the thread: all communication failures are
        caught, logged, and handled via reconnect-with-backoff so a
        single bad read can never crash the process or block FastAPI.
        """
        reconnect_delay = self._settings.serial_reconnect_delay_seconds

        while not self._stop_event.is_set():
            self.status.set_status(ConnectionStatus.WAITING)
            port = self._resolve_port()

            if not port:
                logger.error("No serial port available (configured or auto-detected).")
                self.status.set_status(ConnectionStatus.ERROR)
                if self._sleep_or_stop(reconnect_delay):
                    break
                continue

            try:
                self._reader.open(port)
            except CommunicationError as exc:
                logger.error(f"{exc.message}")
                self.status.set_status(ConnectionStatus.ERROR)
                self.devices.record_error()
                if self._sleep_or_stop(reconnect_delay):
                    break
                reconnect_delay = self._next_backoff(reconnect_delay)
                continue

            self.devices.mark_connected()
            self.status.set_status(ConnectionStatus.CONNECTED)
            reconnect_delay = self._settings.serial_reconnect_delay_seconds  # reset backoff
            logger.info(f"Serial connection established on '{port}'.")

            self._read_loop()

            # _read_loop only returns on disconnect/stop; tear down and retry.
            self._reader.close()
            self.devices.mark_disconnected()

            if self._stop_event.is_set():
                break

            self.status.set_status(ConnectionStatus.WAITING)
            logger.warning(f"Serial connection lost; retrying in {reconnect_delay:.1f}s.")
            if self._sleep_or_stop(reconnect_delay):
                break
            self.devices.record_reconnect()
            reconnect_delay = self._next_backoff(reconnect_delay)

    def _read_loop(self) -> None:
        """Continuously read, parse, validate, and queue packets.

        Returns normally (without raising) whenever the connection is
        lost or a stop has been requested, so :meth:`_run` can decide
        whether to reconnect or exit.
        """
        while not self._stop_event.is_set():
            try:
                line = self._reader.read_line()
            except CommunicationError as exc:
                logger.error(f"Communication error, will attempt to reconnect: {exc.message}")
                self.devices.record_error()
                self.status.set_status(ConnectionStatus.ERROR)
                return

            if line is None:
                continue  # Read timeout with no data; keep waiting without busy-looping.

            packet = self._parser.parse(line)
            if packet is None:
                self.devices.record_error()
                continue

            result = self._validator.validate(packet)
            if not result.is_valid:
                logger.warning(f"Dropping invalid packet: {result.errors}")
                self.devices.record_error()
                continue

            self.queue.put(packet)
            self.devices.record_packet(packet)
            self.status.record_packet_received(packet.timestamp)
            logger.debug(
                f"Packet queued: device={packet.device_id} sequence={packet.sequence} "
                f"readings={len(packet.readings)}"
            )

    def _sleep_or_stop(self, delay_seconds: float) -> bool:
        """Sleep for ``delay_seconds`` without busy-waiting, unless stopped.

        Uses ``Event.wait`` rather than ``time.sleep`` so a stop
        request interrupts the wait immediately instead of after the
        full delay.

        Args:
            delay_seconds: How long to wait before the next attempt.

        Returns:
            ``True`` if a stop was requested during the wait (the
            caller should exit its loop), ``False`` otherwise.
        """
        return self._stop_event.wait(timeout=delay_seconds)

    def _next_backoff(self, current_delay: float) -> float:
        """Compute the next reconnect delay using capped exponential backoff.

        Args:
            current_delay: The delay just used, in seconds.

        Returns:
            The next delay to use, capped at
            ``serial_max_reconnect_delay_seconds``.
        """
        return min(current_delay * 2, self._settings.serial_max_reconnect_delay_seconds)
