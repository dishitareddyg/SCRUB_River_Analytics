"""
hardware/motor_controller.py

Motor state READER (fed by STM32 incoming packets) AND motor command
WRITER (RPi -> STM32).

State tracking:
  IDLE    — left==0 and right==0 as reported by STM32
  MOVING  — at least one motor non-zero
  UNKNOWN — no fresh STM32 data (age > MOTOR_STATE_MAX_AGE_SECONDS)

Command transmission:
  The Navigator only sets the *desired* command (set_desired()).
  A dedicated transmit thread sends exactly ONE documented packet every
  MOTOR_COMMAND_INTERVAL_S (default 2 s):
      {"left":"+100","right":"+100","mode":"auto"}
  When nothing is commanding the motors, the packet is zero ("+0").

  emergency_stop() zeroes the desired command AND writes a zero packet
  immediately (out of cadence) — it never depends on the network.

THREAD SAFETY:
  The serial port is opened by STM32Worker and injected here together
  with a shared write lock so reads and writes never interleave badly.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Optional

try:
    import serial
except ImportError:  # pragma: no cover - exercised on dev machines only
    class _MockSerialModule:
        class SerialException(Exception):
            pass

        class SerialTimeoutException(Exception):
            pass

        class Serial:
            pass

    serial = _MockSerialModule()  # type: ignore

from config.settings import settings
from hardware.protocol import build_motor_command, clamp_pwm
from monitoring.logger import get_logger

logger = get_logger(__name__)


class MotorState(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class MotorControllerWorker:
    def __init__(self, health=None) -> None:
        self._health = health
        self._lock = threading.Lock()
        self._reported_state: MotorState = MotorState.UNKNOWN
        self._reported_left: Optional[float] = None
        self._reported_right: Optional[float] = None
        self._last_update_time: Optional[float] = None

        # Desired command (set by Navigator / MissionManager).
        self._desired_left = 0
        self._desired_right = 0

        # Last transmitted command (telemetry).
        self.last_sent_left = 0
        self.last_sent_right = 0
        self.last_sent_at: Optional[float] = None
        self.packets_sent = 0
        self.send_failures = 0

        # Injected by STM32Worker after the serial port is opened.
        self._serial = None
        self._write_lock: threading.Lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._warned_port_closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MotorCommandTx", daemon=True)
        self._thread.start()
        logger.info("Motor command transmitter started (interval=%.2fs, max=±%d)",
                    settings.MOTOR_COMMAND_INTERVAL_S, settings.MAX_MOTOR_POWER)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        # Final safety stop before the port is closed.
        self.emergency_stop()

    def _run(self) -> None:
        interval = max(0.1, settings.MOTOR_COMMAND_INTERVAL_S)
        next_due = time.monotonic()
        while not self._stop_event.is_set():
            with self._lock:
                left, right = self._desired_left, self._desired_right
            self._write(left, right)
            next_due += interval
            delay = next_due - time.monotonic()
            if delay < 0:  # fell behind (e.g. blocked write) — resync, don't burst
                next_due = time.monotonic()
                delay = 0
            self._stop_event.wait(delay)

    # ------------------------------------------------------------------
    # Desired command (Navigator API)
    # ------------------------------------------------------------------
    def set_desired(self, left: float, right: float) -> None:
        with self._lock:
            self._desired_left = clamp_pwm(left)
            self._desired_right = clamp_pwm(right)

    def set_zero(self) -> None:
        self.set_desired(0, 0)

    @property
    def desired(self) -> tuple[int, int]:
        with self._lock:
            return self._desired_left, self._desired_right

    def emergency_stop(self) -> bool:
        """Zero the desired command and transmit a zero packet immediately."""
        self.set_zero()
        return self._write(0, 0)

    # Backwards-compatible aliases used by the original code base.
    def stop_motors(self) -> bool:
        return self.emergency_stop()

    def send_command(self, left: int, right: int) -> bool:
        self.set_desired(left, right)
        return True

    # ------------------------------------------------------------------
    # State tracking (called on each STM32 packet)
    # ------------------------------------------------------------------
    def update(self, left, right, ts: Optional[float] = None) -> None:
        try:
            left_val = float(left)
            right_val = float(right)
        except (TypeError, ValueError):
            logger.warning("Malformed motors object: left=%r right=%r", left, right)
            return
        new_state = MotorState.IDLE if (left_val == 0 and right_val == 0) else MotorState.MOVING
        now = ts if ts is not None else time.time()
        with self._lock:
            changed = new_state != self._reported_state
            self._reported_state = new_state
            self._reported_left = left_val
            self._reported_right = right_val
            self._last_update_time = now
        if changed:
            logger.info("Motor state → %s (l=%s r=%s)", new_state.value, left, right)
        if self._health:
            self._health.set_motor_state(new_state.value)

    def force_unknown(self) -> None:
        with self._lock:
            self._reported_state = MotorState.UNKNOWN
            self._last_update_time = None
        logger.warning("Motor state forced to UNKNOWN (STM32 disconnect)")
        if self._health:
            self._health.set_motor_state(MotorState.UNKNOWN.value)

    def get_state(self) -> MotorState:
        with self._lock:
            state = self._reported_state
            last_update = self._last_update_time
        if last_update is None or time.time() - last_update > settings.MOTOR_STATE_MAX_AGE_SECONDS:
            return MotorState.UNKNOWN
        return state

    def reported(self) -> dict:
        with self._lock:
            return {"left": self._reported_left, "right": self._reported_right}

    # ------------------------------------------------------------------
    # Serial writing
    # ------------------------------------------------------------------
    def inject_serial(self, ser, write_lock: threading.Lock) -> None:
        self._serial = ser
        self._write_lock = write_lock
        self._warned_port_closed = False

    @property
    def port_open(self) -> bool:
        ser = self._serial
        return ser is not None and bool(getattr(ser, "is_open", False))

    def _write(self, left: int, right: int) -> bool:
        packet = build_motor_command(left, right)
        ser = self._serial
        if ser is None or not getattr(ser, "is_open", False):
            if not self._warned_port_closed:
                logger.warning("Cannot send motor command — serial port not open")
                self._warned_port_closed = True
            self.send_failures += 1
            return False
        try:
            with self._write_lock:
                ser.write(packet)
                flush = getattr(ser, "flush", None)
                if callable(flush):
                    flush()
            self.last_sent_left, self.last_sent_right = left, right
            self.last_sent_at = time.time()
            self.packets_sent += 1
            logger.debug("Motor cmd → %s", packet.decode().strip())
            return True
        except Exception as exc:  # noqa: BLE001 - serial errors vary by platform
            self.send_failures += 1
            logger.error("Motor command write failed: %s", exc)
            return False
