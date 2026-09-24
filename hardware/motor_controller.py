"""
hardware/motor_controller.py

Motor state tracking, fed entirely by the STM32 combined UART packet
(see hardware/stm32.py). There is NO separate Arduino/USB motor link on
the RPi 5 anymore -- motors and the RC controller are wired directly to
the STM32, which reports `motors.left` / `motors.right` inside its 0.5 Hz
JSON packet. This module's sole job remains determining whether the
motors are currently MOVING or IDLE, because sensor acquisition is only
permitted while IDLE (safety-critical rule, spec sections 2, 11, 12) --
it never sends any command anywhere.

State machine (unchanged):
  MOTOR_IDLE    -- confirmed stopped (left == 0 and right == 0), safe to
                   accept sensor samples
  MOTOR_MOVING  -- confirmed moving (left != 0 or right != 0), sensor
                   samples must be rejected
  MOTOR_UNKNOWN -- no recent/valid data (including a stale or lost STM32
                   link) -- sensor samples MUST be rejected (never
                   assume idle)

Freshness is enforced the same way as before: the *reported* state is
only trusted for MOTOR_STATE_MAX_AGE_SECONDS. If the STM32 UART stream
goes stale or disconnects, get_state() naturally reports MOTOR_UNKNOWN
once that window elapses -- and force_unknown() lets the STM32 worker
flag it immediately on a detected disconnect.

Obsolete (removed) with this architecture change:
  - Direct USB serial connection to an Arduino motor controller
    (JSON `{"motor_state": ...}` lines and the legacy
    "CH1=...|L=...R=..." debug text format) -- motors are no longer
    monitored via a separate serial link.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class MotorState(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class MotorControllerWorker:
    """Thread-safe holder for the latest motor state, derived from
    `motors.left` / `motors.right` in each STM32 packet rather than from
    its own serial thread."""

    def __init__(self, health=None):
        self._health = health
        self._lock = threading.Lock()
        self._reported_state: MotorState = MotorState.UNKNOWN
        self._last_update_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle -- kept as no-ops so main.py's start/stop wiring does not
    # need to change: there is no dedicated serial thread to manage now.
    # ------------------------------------------------------------------
    def start(self) -> None:
        logger.info("Motor state now derived from the STM32 UART packet stream (no dedicated Arduino serial link)")

    def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update(self, left, right, ts: Optional[float] = None) -> None:
        """Record a fresh motor reading extracted from an STM32 packet.
        `left == 0 AND right == 0` -> IDLE, otherwise -> MOVING."""
        try:
            left_val = float(left)
            right_val = float(right)
        except (TypeError, ValueError):
            # Malformed motors object -- do not guess; let freshness-based
            # staleness carry the state to UNKNOWN instead of updating it.
            logger.warning("Ignoring malformed motors object: left=%r right=%r", left, right)
            return

        new_state = MotorState.IDLE if (left_val == 0 and right_val == 0) else MotorState.MOVING
        now = ts if ts is not None else time.time()

        with self._lock:
            changed = new_state != self._reported_state
            self._reported_state = new_state
            self._last_update_time = now

        if changed:
            logger.info("Motor state changed to %s (left=%s right=%s)", new_state.value, left, right)

    def force_unknown(self) -> None:
        """Immediately force MOTOR_UNKNOWN, e.g. when the STM32 UART
        link is detected as disconnected -- never assume idle."""
        with self._lock:
            self._reported_state = MotorState.UNKNOWN
            self._last_update_time = None
        if self._health:
            self._health.set_motor_state(MotorState.UNKNOWN.value)

    def get_state(self) -> MotorState:
        """Authoritative current motor state, applying the freshness rule."""
        with self._lock:
            state, last_update = self._reported_state, self._last_update_time

        if last_update is None:
            return MotorState.UNKNOWN
        if time.time() - last_update > settings.MOTOR_STATE_MAX_AGE_SECONDS:
            return MotorState.UNKNOWN
        return state
