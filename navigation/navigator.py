"""
navigation/navigator.py

The central navigation state machine.  Runs in its own background thread
and sends motor commands to the STM32 at NAV_COMMAND_INTERVAL_S.

STATE MACHINE
=============
IDLE            → waiting for a mission to be loaded
NAVIGATING      → moving toward current grid's centre point
COLLECTING      → within arrival radius, motors stopped, sensor pipeline active
PAUSED          → operator-requested pause (motors stopped)
COMPLETE        → all grids in the mission visited and collected
GPS_LOST        → GPS watchdog expired while navigating → motors stopped
GEOFENCE_STOP   → bot drifted outside GEOFENCE_RADIUS_M → motors stopped
ERROR           → unrecoverable internal error

TRANSITIONS
===========
IDLE         --[mission loaded]----------→ NAVIGATING
NAVIGATING   --[dist ≤ arrival_radius]--→ COLLECTING
COLLECTING   --[grid session complete]--→ NAVIGATING (next grid)
                                        → COMPLETE   (last grid done)
NAVIGATING   --[GPS watchdog expires]---→ GPS_LOST
NAVIGATING   --[geofence breach]--------→ GEOFENCE_STOP
NAVIGATING   --[mission timer expired]--→ ERROR
Any RUNNING  --[cmd_pause()]------------→ PAUSED
PAUSED       --[cmd_resume()]----------→ (previous active state)
Any          --[cmd_abort()]------------→ IDLE

GRID COLLECTION HANDOFF
========================
When the bot arrives at a grid:
  1. Navigator sends stop command (left=0, right=0).
  2. Navigator sets state = COLLECTING and notifies MeasurementManager
     that it may now begin collecting sensor samples via on_grid_arrived().
  3. MeasurementManager collects MAX_READINGS_PER_GRID samples
     (driven by incoming STM32 packets at the cadence gate) and calls
     navigator.on_grid_collection_complete() when done.
  4. Navigator advances to the next grid and sets state = NAVIGATING.
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Callable, List, Optional

from config.settings import settings
from hardware.gps import GPSFix, GPSWorker
from hardware.motor_controller import MotorControllerWorker
from monitoring.logger import get_logger
from navigation.steering import (
    compute_wheel_powers,
    haversine_distance,
    initial_bearing,
    normalize_heading_error,
)

logger = get_logger(__name__)


class NavState(str, Enum):
    IDLE = "IDLE"
    NAVIGATING = "NAVIGATING"
    COLLECTING = "COLLECTING"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"
    GPS_LOST = "GPS_LOST"
    GEOFENCE_STOP = "GEOFENCE_STOP"
    ERROR = "ERROR"


# States that count as "active" (bot is doing mission work)
_ACTIVE_STATES = {NavState.NAVIGATING, NavState.COLLECTING}


class Navigator:
    """
    Runs the navigation state machine in a background thread, issuing
    motor commands to the STM32 every NAV_COMMAND_INTERVAL_S.

    Lifecycle:
        nav = Navigator(gps, motor, health)
        nav.load_mission(waypoints)   # list of {grid_id, lat, lon} dicts
        nav.start()
        ...
        nav.stop()
    """

    def __init__(
        self,
        gps: GPSWorker,
        motor: MotorControllerWorker,
        health=None,
        on_grid_arrived: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._gps = gps
        self._motor = motor
        self._health = health

        # Callback invoked when the bot arrives at a grid centre.
        # MeasurementManager registers this to start collecting.
        self._on_grid_arrived = on_grid_arrived

        # Mission state
        self._state: NavState = NavState.IDLE
        self._state_lock = threading.Lock()
        self._waypoints: List[dict] = []          # list of {grid_id, lat, lon, ...}
        self._waypoint_index: int = 0
        self._mission_id: Optional[str] = None

        # Safety
        self._gps_last_valid: float = time.monotonic()
        self._mission_start: Optional[float] = None
        self._geofence_origin_lat: Optional[float] = None
        self._geofence_origin_lon: Optional[float] = None

        # Last commanded PWM (for telemetry)
        self.last_left_pwm: int = 0
        self.last_right_pwm: int = 0

        # Background nav thread
        self._stop_event = threading.Event()
        self._collection_done = threading.Event()  # set by on_grid_collection_complete
        self._thread: Optional[threading.Thread] = None

        # Pause support: store the state to resume to
        self._pre_pause_state: Optional[NavState] = None

    # ------------------------------------------------------------------
    # Mission loading
    # ------------------------------------------------------------------
    def load_mission(self, waypoints: List[dict], mission_id: Optional[str] = None) -> None:
        """
        Load an ordered list of grid waypoints.
        Each waypoint: {"grid_id": str, "lat": float, "lon": float,
                        "grid_code": str, ...}
        """
        with self._state_lock:
            self._waypoints = list(waypoints)
            self._waypoint_index = 0
            self._mission_id = mission_id
        logger.info(
            "Mission loaded: %d grid(s) [mission_id=%s]", len(waypoints), mission_id
        )
        if self._health:
            self._health.set_mission(mission_id, 0, len(waypoints))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="NavigatorThread", daemon=True
        )
        self._thread.start()
        logger.info("Navigator thread started")

    def stop(self) -> None:
        self._stop_event.set()
        self._collection_done.set()  # unblock any waiting
        if self._thread:
            self._thread.join(timeout=5)
        self._motor.stop_motors()
        logger.info("Navigator stopped")

    # ------------------------------------------------------------------
    # External control commands
    # ------------------------------------------------------------------
    def cmd_start(self) -> None:
        with self._state_lock:
            if self._state != NavState.IDLE:
                logger.warning("cmd_start ignored in state %s", self._state)
                return
            if not self._waypoints:
                logger.error("cmd_start rejected: no waypoints loaded")
                return
            self._waypoint_index = 0
            self._mission_start = time.monotonic()
            self._state = NavState.NAVIGATING
        logger.info("Mission started → NAVIGATING")

    def cmd_pause(self) -> None:
        with self._state_lock:
            if self._state in _ACTIVE_STATES:
                self._pre_pause_state = self._state
                self._state = NavState.PAUSED
                self._motor.stop_motors()
                logger.info("Mission PAUSED")
            else:
                logger.warning("cmd_pause ignored in state %s", self._state)

    def cmd_resume(self) -> None:
        with self._state_lock:
            if self._state == NavState.PAUSED and self._pre_pause_state:
                self._state = self._pre_pause_state
                self._pre_pause_state = None
                logger.info("Mission RESUMED → %s", self._state)
            else:
                logger.warning("cmd_resume ignored in state %s", self._state)

    def cmd_abort(self) -> None:
        with self._state_lock:
            logger.info("Mission ABORTED from state %s", self._state)
            self._state = NavState.IDLE
            self._waypoints = []
            self._waypoint_index = 0
            self._mission_id = None
        self._motor.stop_motors()
        self._collection_done.set()

    # ------------------------------------------------------------------
    # Called by MeasurementManager when sensor collection is done for
    # the current grid (MAX_READINGS_PER_GRID samples accepted).
    # ------------------------------------------------------------------
    def on_grid_collection_complete(self) -> None:
        logger.info(
            "Grid %d/%d collection complete",
            self._waypoint_index + 1,
            len(self._waypoints),
        )
        self._collection_done.set()

    @property
    def state(self) -> NavState:
        with self._state_lock:
            return self._state

    @property
    def current_waypoint(self) -> Optional[dict]:
        with self._state_lock:
            if 0 <= self._waypoint_index < len(self._waypoints):
                return self._waypoints[self._waypoint_index]
        return None

    # ------------------------------------------------------------------
    # Background navigation thread
    # ------------------------------------------------------------------
    def _run(self) -> None:
        """Main loop: executes one nav tick every NAV_COMMAND_INTERVAL_S."""
        while not self._stop_event.is_set():
            tick_start = time.monotonic()

            with self._state_lock:
                state = self._state

            if state == NavState.NAVIGATING:
                self._tick_navigating()
            elif state == NavState.COLLECTING:
                self._tick_collecting()
            elif state in (NavState.PAUSED, NavState.IDLE):
                pass  # motors already stopped; wait
            elif state in (
                NavState.COMPLETE, NavState.GPS_LOST,
                NavState.GEOFENCE_STOP, NavState.ERROR,
            ):
                # Terminal states — stop and wait for reset.
                self._motor.stop_motors()

            elapsed = time.monotonic() - tick_start
            sleep = max(0.0, settings.NAV_COMMAND_INTERVAL_S - elapsed)
            self._stop_event.wait(sleep)

    # ------------------------------------------------------------------
    def _tick_navigating(self) -> None:
        """One steering tick while NAVIGATING."""
        fix = self._gps.get_fix()

        # --- GPS watchdog ---
        if fix.valid:
            self._gps_last_valid = time.monotonic()
        else:
            if (time.monotonic() - self._gps_last_valid) > settings.GPS_LOSS_TIMEOUT_S:
                self._transition(NavState.GPS_LOST, "GPS watchdog expired")
                self._motor.stop_motors()
                return

        # --- Mission timer ---
        if (
            self._mission_start is not None
            and (time.monotonic() - self._mission_start) > settings.MAX_MISSION_RUNTIME_S
        ):
            self._transition(NavState.ERROR, "max mission runtime exceeded")
            self._motor.stop_motors()
            return

        if not fix.valid or fix.latitude is None or fix.longitude is None:
            # No fix yet — send zero (hold) and wait.
            self._motor.send_command(0, 0)
            return

        # --- Geofence check ---
        if self._geofence_origin_lat is None:
            # Latch origin on first valid fix.
            self._geofence_origin_lat = fix.latitude
            self._geofence_origin_lon = fix.longitude

        if settings.GEOFENCE_RADIUS_M > 0:
            dist_from_origin = haversine_distance(
                fix.latitude, fix.longitude,
                self._geofence_origin_lat, self._geofence_origin_lon,
            )
            if dist_from_origin > settings.GEOFENCE_RADIUS_M:
                self._transition(NavState.GEOFENCE_STOP, "geofence breach")
                self._motor.stop_motors()
                return

        with self._state_lock:
            idx = self._waypoint_index
            waypoints = self._waypoints

        if idx >= len(waypoints):
            self._transition(NavState.COMPLETE, "all grids visited")
            self._motor.stop_motors()
            return

        wp = waypoints[idx]
        dist = haversine_distance(fix.latitude, fix.longitude, wp["lat"], wp["lon"])

        logger.debug(
            "NAVIGATING → grid %d/%d (%s) dist=%.1f m",
            idx + 1, len(waypoints), wp.get("grid_code", wp["grid_id"]), dist,
        )

        # --- Arrival check ---
        if dist <= settings.WAYPOINT_ARRIVAL_RADIUS_M:
            logger.info(
                "Arrived at grid %d/%d (%s) — dist=%.2f m",
                idx + 1, len(waypoints), wp.get("grid_code", wp["grid_id"]), dist,
            )
            self._motor.stop_motors()
            self._transition(NavState.COLLECTING, f"arrived at grid {wp.get('grid_code', wp['grid_id'])}")
            # Notify MeasurementManager to begin collection.
            if self._on_grid_arrived:
                try:
                    self._on_grid_arrived(wp)
                except Exception as exc:  # noqa: BLE001
                    logger.error("on_grid_arrived callback error: %s", exc)
            return

        # --- Steering ---
        heading = fix.heading  # compass heading from STM32 packet
        if heading is None:
            # Fallback: we cannot steer without heading — hold and warn.
            logger.warning("No compass heading — holding position")
            self._motor.send_command(0, 0)
            return

        target_bearing = initial_bearing(
            fix.latitude, fix.longitude, wp["lat"], wp["lon"]
        )
        error = normalize_heading_error(target_bearing, heading)

        left, right = compute_wheel_powers(
            heading_error_deg=error,
            cruise_power=settings.DEFAULT_CRUISE_POWER,
            steering_k=settings.STEERING_K,
            max_power=settings.MAX_MOTOR_POWER,
        )

        self._motor.send_command(left, right)
        self.last_left_pwm = left
        self.last_right_pwm = right

    # ------------------------------------------------------------------
    def _tick_collecting(self) -> None:
        """
        While COLLECTING the Navigator holds motors stopped and waits for
        MeasurementManager to call on_grid_collection_complete().
        The event is checked each tick; once set the Navigator advances.
        """
        self._motor.stop_motors()  # belt-and-suspenders

        if self._collection_done.is_set():
            self._collection_done.clear()
            self._advance_to_next_grid()

    def _advance_to_next_grid(self) -> None:
        with self._state_lock:
            self._waypoint_index += 1
            total = len(self._waypoints)
            idx = self._waypoint_index

        if self._health:
            self._health.set_mission(self._mission_id, idx, total)

        if idx >= total:
            self._transition(NavState.COMPLETE, "all grids collected")
            logger.info("Mission COMPLETE — all %d grids done", total)
        else:
            wp = self._waypoints[idx]
            self._transition(
                NavState.NAVIGATING,
                f"heading to grid {idx + 1}/{total} ({wp.get('grid_code', wp['grid_id'])})",
            )

    # ------------------------------------------------------------------
    def _transition(self, new_state: NavState, detail: str = "") -> None:
        with self._state_lock:
            old = self._state
            self._state = new_state
        msg = f"{old.value} → {new_state.value}" + (f": {detail}" if detail else "")
        logger.info("NAV STATE: %s", msg)
        if self._health:
            self._health.set_nav_state(new_state.value)
