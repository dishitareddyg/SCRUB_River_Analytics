"""
hardware/stm32.py

Dedicated worker that continuously listens on UART for the STM32's
combined telemetry packet (newline-delimited JSON, sent at 0.5 Hz --
approximately every SENSOR_PACKET_INTERVAL_SECONDS).

This is now the SOLE hardware input to the RPi 5: all sensors, the
NEO-M8N GPS/compass, motors and the RC controller are wired to the
STM32, which relays everything to the RPi in one packet per cycle:

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

Robustness requirements implemented here (spec section 10), carried over
unchanged from the previous single-purpose sensor-packet reader:
  - handles newline-delimited JSON
  - handles partial serial reads (line buffering across read() calls)
  - handles malformed packets (JSON errors are caught & logged, never raised)
  - handles extra whitespace
  - handles unexpected/extra fields (ignored)
  - never crashes the backend because of one bad packet

This module's only job is reliable framing + parsing + minimal shape
validation (must decode to a JSON object). It does not interpret
motors/gps/compass/sensors semantically -- that is fully the
responsibility of the callback (MeasurementManager.on_stm32_packet),
exactly as the previous version left "sensors" business validation to
its callback.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

import serial

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)

PacketCallback = Callable[[dict], None]


class STM32Worker:
    def __init__(self, on_packet: PacketCallback, health=None, on_disconnect: Optional[Callable[[], None]] = None):
        self._on_packet = on_packet
        self._on_disconnect = on_disconnect
        self._health = health
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial: Optional[serial.Serial] = None
        self._buffer = b""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="STM32Worker", daemon=True)
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
            )
            logger.info("STM32 serial connected on %s", settings.STM32_SERIAL_PORT)
            if self._health:
                self._health.set_stm32_connected(True)
            return True
        except serial.SerialException as exc:
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

    def _notify_disconnect(self) -> None:
        # Communication with the STM32 (and therefore GPS/compass/motors/
        # sensors, all of which ride on this single link) is lost --
        # let the callback wiring force motor state to UNKNOWN immediately
        # rather than waiting out MOTOR_STATE_MAX_AGE_SECONDS.
        if self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in STM32 on_disconnect callback: %s", exc)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._serial is None:
                if not self._open_serial():
                    time.sleep(settings.MQTT_RECONNECT_DELAY)
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
                time.sleep(settings.MQTT_RECONNECT_DELAY)
            except Exception as exc:  # noqa: BLE001 - one bad packet must never crash us
                logger.error("Unexpected STM32 worker error: %s", exc)
                time.sleep(0.2)

    def _drain_lines(self) -> None:
        while b"\n" in self._buffer:
            raw_line, self._buffer = self._buffer.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self._handle_line(line)
        # Guard against a runaway buffer if a malformed stream never sends '\n'
        if len(self._buffer) > 8192:
            logger.warning("STM32 buffer overflow without newline -- discarding buffer")
            self._buffer = b""

    def _handle_line(self, line: str) -> None:
        try:
            packet = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Malformed STM32 packet discarded: %r", line[:200])
            return

        if not isinstance(packet, dict):
            logger.warning("STM32 packet is not a JSON object, discarded: %r", line[:200])
            return

        if self._health:
            self._health.set_last_sensor_packet_time(time.time())

        try:
            self._on_packet(packet)
        except Exception as exc:  # noqa: BLE001 - never let a callback error kill the reader
            logger.error("Error while processing STM32 packet: %s", exc)
