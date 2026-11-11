"""
hardware/stm32.py

Dedicated worker that continuously reads from the UART connection to
the STM32 microcontroller (line-buffered JSON, 1 packet every 2 s)
AND shares that open serial port with MotorControllerWorker so nav
commands can be written back on the same link.

Incoming packet format (STM32 → RPi, 1 packet / 2 s):
{
  "device_id": "BOT001",
  "timestamp": "...",
  "motors": {"left": 0, "right": 0},
  "gps": {"latitude": 12.123456, "longitude": 77.123456},
  "compass": {"heading": 182.4},
  "sensors": {
    "ph": 7.12, "tds": 214.2, "turbidity": 15.3,
    "temperature_c": 27.4, "humidity_percent": 71.2
  }
}

Outgoing packet format (RPi → STM32, every MOTOR_COMMAND_INTERVAL_S = 2 s):
{"left": "+100", "right": "+100", "mode": "auto"}
  — written by MotorControllerWorker (transmit thread) via the shared port.

Robustness:
  - Handles partial reads via line buffering (b"\\n"-delimited).
  - Malformed / non-dict JSON → logged and discarded, never raised.
  - Buffer overflow guard at 8 192 bytes without a newline.
  - Auto-reconnect on SerialException (STM32_RECONNECT_DELAY_S).
  - on_disconnect callback → MotorControllerWorker.force_unknown()
  - Shared serial port: all WRITES are gated on _write_lock so reading
    and writing never interleave on the wire.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

try:
    import serial
except ImportError:
    class _MockSerialModule:
        class SerialException(Exception):
            pass
        class Serial:
            pass
    serial = _MockSerialModule()  # type: ignore

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)

PacketCallback = Callable[[dict], None]


class STM32Worker:
    def __init__(
        self,
        on_packet: PacketCallback,
        motor_controller,          # MotorControllerWorker
        health=None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_packet = on_packet
        self._motor = motor_controller
        self._health = health
        self._on_disconnect = on_disconnect
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial: Optional[serial.Serial] = None
        # Shared write lock — injected into MotorControllerWorker after open.
        self._write_lock = threading.Lock()
        self._buffer = b""
        self.last_packet_time: Optional[float] = None
        self.packets_received = 0
        self.packets_malformed = 0

    @property
    def connected(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    @property
    def link_alive(self) -> bool:
        """True if a valid packet arrived within STM32_LINK_TIMEOUT_S."""
        return (self.last_packet_time is not None
                and time.time() - self.last_packet_time <= settings.STM32_LINK_TIMEOUT_S)

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="STM32Worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "STM32 UART worker started (port=%s baud=%s)",
            settings.STM32_SERIAL_PORT,
            settings.STM32_BAUDRATE,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._close_serial()

    # ------------------------------------------------------------------
    def _open_serial(self) -> bool:
        try:
            self._serial = serial.Serial(
                port=settings.STM32_SERIAL_PORT,
                baudrate=settings.STM32_BAUDRATE,
                timeout=settings.STM32_SERIAL_TIMEOUT,
                write_timeout=settings.STM32_WRITE_TIMEOUT,
            )
            # Share port + write lock with MotorControllerWorker.
            self._motor.inject_serial(self._serial, self._write_lock)
            logger.info("STM32 serial connected on %s", settings.STM32_SERIAL_PORT)
            if self._health:
                self._health.set_stm32_connected(True)
            return True
        except Exception as exc:  # noqa: BLE001 - SerialException, OSError, missing pyserial
            logger.warning("STM32 serial connection failed: %s", exc)
            if self._health:
                self._health.set_stm32_connected(False)
            self._notify_disconnect()
            self._serial = None
            return False

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None
        # Revoke the motor controller's serial reference.
        self._motor.inject_serial(None, self._write_lock)  # type: ignore[arg-type]

    def _notify_disconnect(self) -> None:
        if self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in STM32 on_disconnect callback: %s", exc)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._serial is None:
                if not self._open_serial():
                    self._stop_event.wait(settings.STM32_RECONNECT_DELAY_S)
                    continue

            try:
                chunk = self._serial.read(256)
                if not chunk:
                    continue
                self._buffer += chunk
                self._drain_lines()
            except (serial.SerialException, OSError) as exc:
                logger.warning("STM32 serial error, reconnecting: %s", exc)
                if self._health:
                    self._health.set_stm32_connected(False)
                self._notify_disconnect()
                self._close_serial()
                self._stop_event.wait(settings.STM32_RECONNECT_DELAY_S)
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected STM32 worker error: %s", exc)
                time.sleep(0.2)

    def _drain_lines(self) -> None:
        while b"\n" in self._buffer:
            raw_line, self._buffer = self._buffer.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self._handle_line(line)
        if len(self._buffer) > 8192:
            logger.warning("STM32 buffer overflow — discarding")
            self._buffer = b""

    def _handle_line(self, line: str) -> None:
        try:
            packet = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            self.packets_malformed += 1
            logger.warning("Malformed STM32 packet discarded: %r", line[:200])
            return

        if not isinstance(packet, dict):
            self.packets_malformed += 1
            logger.warning("STM32 packet not a JSON object: %r", line[:200])
            return

        self.last_packet_time = time.time()
        self.packets_received += 1
        if self._health:
            self._health.set_last_sensor_packet_time(time.time())

        try:
            self._on_packet(packet)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing STM32 packet: %s", exc)
