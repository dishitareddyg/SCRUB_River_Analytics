"""
hardware/motor_controller.py

Motor state READER (fed by STM32 incoming packets) AND motor command
WRITER (sends RPi→STM32 nav commands).

State tracking (same as SCRUB):
  IDLE    — left==0 and right==0 as reported by STM32, safe for sensor sampling
  MOVING  — at least one motor non-zero
  UNKNOWN — no fresh STM32 data (age > MOTOR_STATE_MAX_AGE_SECONDS)

Command sending (NEW for autonomous nav):
  send_command(left, right) serialises a nav packet and writes it to the
  shared serial port provided at construction time.  The packet format is:
    {"left": "+100", "right": "+100", "mode": "auto"}
  PWM values are clamped to ±MAX_MOTOR_POWER.  The NavigationWorker calls
  this at NAV_COMMAND_INTERVAL_S via its own background thread.

THREAD SAFETY:
  The serial port is shared between STM32Worker (reader) and
  MotorCommandWorker (writer).  A single threading.Lock guards all writes.
  Reads happen in STM32Worker which uses the same lock via
  _write_lock_ref injected at construction.
"""

from __future__ import annotations

import json
import threading
import time
from enum import Enum
from typing import Optional

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


class MotorState(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class MotorControllerWorker:
    """
    Thread-safe tracker for the latest motor state derived from STM32
    incoming packets.  Also exposes send_command() to write motor-command
    packets back to the STM32 over the shared serial connection.

    The serial.Serial instance is created by STM32Worker and injected here
    so both share the same open port.  Writing is guarded by write_lock
    (also injected), which STM32Worker holds during writes if needed.
    """

    def __init__(self, health=None) -> None:
        self._health = health
        self._lock = threading.Lock()
        self._reported_state: MotorState = MotorState.UNKNOWN
        self._last_update_time: Optional[float] = None

        # Injected by STM32Worker after the serial port is opened.
        self._serial: Optional[serial.Serial] = None
        self._write_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle (no-op; state is driven by STM32Worker callbacks)
    # ------------------------------------------------------------------
    def start(self) -> None:
        logger.info("MotorControllerWorker: state derived from STM32 packet stream.")

    def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # State tracking (called by Navigator/MeasurementManager on each packet)
    # ------------------------------------------------------------------
    def update(self, left, right, ts: Optional[float] = None) -> None:
        """Update motor state from motors.left/right in an STM32 packet."""
        try:
            left_val = float(left)
            right_val = float(right)
        except (TypeError, ValueError):
            logger.warning("Malformed motors object: left=%r right=%r", left, right)
            return

        new_state = (
            MotorState.IDLE if (left_val == 0 and right_val == 0) else MotorState.MOVING
        )
        now = ts if ts is not None else time.time()

        with self._lock:
            changed = new_state != self._reported_state
            self._reported_state = new_state
            self._last_update_time = now

        if changed:
            logger.info(
                "Motor state → %s (l=%s r=%s)", new_state.value, left, right
            )
        if self._health:
            self._health.set_motor_state(new_state.value)

    def force_unknown(self) -> None:
        """Immediately force UNKNOWN, e.g. on STM32 disconnect."""
        with self._lock:
            self._reported_state = MotorState.UNKNOWN
            self._last_update_time = None
        logger.warning("Motor state forced to UNKNOWN (STM32 disconnect)")
        if self._health:
            self._health.set_motor_state(MotorState.UNKNOWN.value)

    def get_state(self) -> MotorState:
        """Authoritative motor state with freshness check."""
        with self._lock:
            state = self._reported_state
            last_update = self._last_update_time
        if last_update is None:
            return MotorState.UNKNOWN
        if time.time() - last_update > settings.MOTOR_STATE_MAX_AGE_SECONDS:
            return MotorState.UNKNOWN
        return state

    # ------------------------------------------------------------------
    # Command writing (RPi → STM32)
    # ------------------------------------------------------------------
    def inject_serial(self, ser: serial.Serial, write_lock: threading.Lock) -> None:
        """Called by STM32Worker once the serial port is open."""
        self._serial = ser
        self._write_lock = write_lock

    def send_command(self, left: int, right: int) -> bool:
        """
        Send a motor command packet to the STM32.
        PWM values are clamped to ±MAX_MOTOR_POWER.
        Returns True on success, False on serial error.

        Packet format: {"left": "+100", "right": "+100", "mode": "auto"}
        """
        max_p = settings.MAX_MOTOR_POWER
        left_c = max(-max_p, min(max_p, int(round(left))))
        right_c = max(-max_p, min(max_p, int(round(right))))

        # Format with explicit sign to match protocol spec.
        left_str = f"+{left_c}" if left_c >= 0 else str(left_c)
        right_str = f"+{right_c}" if right_c >= 0 else str(right_c)

        packet = json.dumps(
            {"left": left_str, "right": right_str, "mode": "auto"},
            separators=(",", ":"),
        ) + "\n"

        if self._serial is None or not self._serial.is_open:
            logger.warning("Cannot send motor command — serial port not open")
            return False

        try:
            with self._write_lock:
                self._serial.write(packet.encode("utf-8"))
            logger.debug("Motor cmd → left=%s right=%s", left_str, right_str)
            return True
        except (serial.SerialException, OSError) as exc:
            logger.error("Motor command write failed: %s", exc)
            return False

    def stop_motors(self) -> bool:
        """Convenience: send a full-stop command."""
        return self.send_command(0, 0)
