"""
navigation/navigator.py

Global GPS waypoint follower: GCS -> polygon traversal -> GCS.

The Navigator never talks to Supabase.  It receives the locally stored
waypoints from MissionManager and, every NAV_UPDATE_INTERVAL_S:

  1. reads the latest GPS fix + compass heading (from the STM32 packet)
  2. distance + bearing to the current target waypoint
  3. heading error -> proportional differential steering (steering.py)
  4. sets the desired motor command (transmitted by MotorControllerWorker
     as the documented {"left":"+N","right":"+N","mode":"auto"} packet)
  5. on arrival (<= WAYPOINT_ARRIVAL_RADIUS_M) advances to the next one
  6. after the final GCS waypoint: motors 0, mission complete

NAV STATES
  IDLE        no mission loaded in the navigator; motors 0
  NAVIGATING  steering toward the current target
  HOLDING     temporarily holding (motors 0): GPS stale, compass missing,
              STM32 link down.  Escalates to a fault after GPS_LOSS_TIMEOUT_S
  PAUSED      operator pause or fault; motors 0; waits for resume
  COMPLETED   final GCS waypoint reached; motors 0

Faults are reported to MissionManager through on_fault(reason, fatal):
  non-fatal (GPS_LOST, COMPASS_LOST, STM32_LINK_LOST, GEOFENCE,
  WAYPOINT_TIMEOUT) -> mission PAUSED, operator must resume
  fatal (MAX_RUNTIME, INTERNAL_ERROR) -> mission FAILED
Callbacks are always invoked OUTSIDE the navigator lock.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, List, Optional

from config.settings import settings
from hardware.gps import GPSWorker
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
    HOLDING = "HOLDING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class Navigator:
    def __init__(
        self,
        gps: GPSWorker,
        motor: MotorControllerWorker,
        health=None,
        link_ok: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._gps = gps
        self._motor = motor
        self._health = health
        self._link_ok = link_ok or (lambda: True)

        # Callbacks wired by MissionManager.
        self.on_waypoint_reached: Optional[Callable[[str, int, int, int], None]] = None
        self.on_mission_complete: Optional[Callable[[str], None]] = None
        self.on_fault: Optional[Callable[[str, str, bool], None]] = None

        self._lock = threading.RLock()
        self._state = NavState.IDLE
        self._mission_id: Optional[str] = None
        self._waypoints: List[dict] = []
        self._index = 0
        self._active_since: Optional[float] = None      # monotonic
        self._active_elapsed = 0.0                      # runtime before last resume
        self._target_since: Optional[float] = None
        self._hold_since: Optional[float] = None
        self._hold_reason: Optional[str] = None
        self._gcs: Optional[tuple[float, float]] = None
        self._status: dict = {}

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="Navigator", daemon=True)
        self._thread.start()
        logger.info("Navigator started (update=%.2fs, arrival=%.1fm)",
                    settings.NAV_UPDATE_INTERVAL_S, settings.WAYPOINT_ARRIVAL_RADIUS_M)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._motor.emergency_stop()

    # ------------------------------------------------------------------
    # Commands (called by MissionManager)
    # ------------------------------------------------------------------
    def begin(self, mission_id: str, waypoints: List[dict], start_index: int = 0,
              elapsed_runtime_s: float = 0.0) -> None:
        if not waypoints:
            raise ValueError("no waypoints")
        gcs_wp = waypoints[0]
        with self._lock:
            self._mission_id = mission_id
            self._waypoints = list(waypoints)
            self._index = max(0, min(start_index, len(waypoints) - 1))
            self._gcs = (gcs_wp["latitude"], gcs_wp["longitude"])
            self._active_since = time.monotonic()
            self._active_elapsed = elapsed_runtime_s
            self._target_since = time.monotonic()
            self._hold_since = None
            self._hold_reason = None
            self._state = NavState.NAVIGATING
        self._publish_state()
        logger.info("Navigator: mission %s NAVIGATING from waypoint %d/%d",
                    mission_id, self._index, len(waypoints) - 1)

    def pause(self) -> None:
        with self._lock:
            if self._active_since is not None:
                self._active_elapsed += time.monotonic() - self._active_since
                self._active_since = None
            if self._state in (NavState.NAVIGATING, NavState.HOLDING):
                self._state = NavState.PAUSED
        self._motor.emergency_stop()
        self._publish_state()

    def clear(self) -> None:
        """Forget the mission (abort / complete). Motors zeroed immediately."""
        with self._lock:
            self._state = NavState.IDLE
            self._mission_id = None
            self._waypoints = []
            self._index = 0
            self._active_since = None
            self._active_elapsed = 0.0
            self._status = {}
        self._motor.emergency_stop()
        self._publish_state()

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------
    @property
    def state(self) -> NavState:
        with self._lock:
            return self._state

    @property
    def mission_id(self) -> Optional[str]:
        with self._lock:
            return self._mission_id

    @property
    def current_index(self) -> int:
        with self._lock:
            return self._index

    def runtime_s(self) -> float:
        with self._lock:
            extra = time.monotonic() - self._active_since if self._active_since else 0.0
            return self._active_elapsed + extra

    def status(self) -> dict:
        with self._lock:
            target = self._waypoints[self._index] if 0 <= self._index < len(self._waypoints) else None
            return {
                "nav_state": self._state.value,
                "mission_id": self._mission_id,
                "current_waypoint_index": self._index,
                "total_waypoints": len(self._waypoints),
                "target_waypoint": dict(target) if target else None,
                "hold_reason": self._hold_reason,
                **self._status,
            }

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------
    def _run(self) -> None:
        interval = max(0.1, settings.NAV_UPDATE_INTERVAL_S)
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Navigator tick error: %s", exc)
                self._fault("INTERNAL_ERROR", fatal=True)
            self._stop_event.wait(max(0.0, interval - (time.monotonic() - started)))

    def tick(self) -> None:
        """One navigation step (public for deterministic tests)."""
        events: list[tuple] = []
        with self._lock:
            state = self._state
            if state not in (NavState.NAVIGATING, NavState.HOLDING):
                self._motor.set_zero()
                return
            mission_id = self._mission_id

            # --- runtime limit (fatal) ---
            if settings.MAX_MISSION_RUNTIME_S > 0 and self.runtime_s() > settings.MAX_MISSION_RUNTIME_S:
                events.append(("fault", "MAX_RUNTIME", True))
            else:
                events.extend(self._tick_locked(mission_id))
        for ev in events:
            if ev[0] == "fault":
                self._fault(ev[1], fatal=ev[2])
            elif ev[0] == "reached" and self.on_waypoint_reached:
                self._safe(self.on_waypoint_reached, *ev[1:])
            elif ev[0] == "complete" and self.on_mission_complete:
                self._safe(self.on_mission_complete, ev[1])
        self._publish_state()

    def _hold(self, reason: str) -> list[tuple]:
        """Hold position (motors 0); escalate after GPS_LOSS_TIMEOUT_S."""
        self._motor.set_zero()
        now = time.monotonic()
        if self._hold_reason != reason or self._hold_since is None:
            self._hold_since = now
            self._hold_reason = reason
            logger.warning("Navigator HOLDING: %s", reason)
        self._state = NavState.HOLDING
        if now - self._hold_since > settings.GPS_LOSS_TIMEOUT_S:
            return [("fault", reason, False)]
        return []

    def _tick_locked(self, mission_id: str) -> list[tuple]:
        if not self._link_ok():
            return self._hold("STM32_LINK_LOST")

        fix = self._gps.get_fix()
        if not fix.valid:
            return self._hold("GPS_LOST")
        if not fix.heading_valid:
            return self._hold("COMPASS_LOST")

        if self._state == NavState.HOLDING:
            logger.info("Navigator: %s recovered, resuming NAVIGATING", self._hold_reason)
            self._target_since = time.monotonic()  # do not count hold time
        self._state = NavState.NAVIGATING
        self._hold_since = None
        self._hold_reason = None

        # --- geofence around the GCS ---
        if settings.GEOFENCE_RADIUS_M > 0 and self._gcs:
            if haversine_distance(fix.latitude, fix.longitude, *self._gcs) > settings.GEOFENCE_RADIUS_M:
                self._motor.set_zero()
                return [("fault", "GEOFENCE", False)]

        events: list[tuple] = []
        total = len(self._waypoints)
        # Arrival may cascade (e.g. first GCS waypoint while sitting at GCS).
        while self._index < total:
            wp = self._waypoints[self._index]
            dist = haversine_distance(fix.latitude, fix.longitude, wp["latitude"], wp["longitude"])
            if dist > settings.WAYPOINT_ARRIVAL_RADIUS_M:
                break
            logger.info("Reached waypoint %d/%d (%s) dist=%.2fm",
                        self._index, total - 1, wp.get("type"), dist)
            seq = wp["sequence_order"]
            self._index += 1
            self._target_since = time.monotonic()
            events.append(("reached", mission_id, seq, self._index, total))

        if self._index >= total:
            self._motor.set_zero()
            self._index = total - 1
            self._state = NavState.COMPLETED
            self._status.update(distance_to_target_m=0.0, heading_error_deg=0.0,
                                desired_left=0, desired_right=0)
            logger.info("Mission %s: final GCS waypoint reached — COMPLETED", mission_id)
            events.append(("complete", mission_id))
            return events

        if (settings.WAYPOINT_TIMEOUT_S > 0 and self._target_since is not None
                and time.monotonic() - self._target_since > settings.WAYPOINT_TIMEOUT_S):
            self._motor.set_zero()
            events.append(("fault", "WAYPOINT_TIMEOUT", False))
            return events

        wp = self._waypoints[self._index]
        dist = haversine_distance(fix.latitude, fix.longitude, wp["latitude"], wp["longitude"])
        bearing = initial_bearing(fix.latitude, fix.longitude, wp["latitude"], wp["longitude"])
        error = normalize_heading_error(bearing, fix.heading)

        cruise = settings.DEFAULT_CRUISE_POWER
        if settings.APPROACH_SLOWDOWN_RADIUS_M > 0 and dist < settings.APPROACH_SLOWDOWN_RADIUS_M:
            scale = dist / settings.APPROACH_SLOWDOWN_RADIUS_M
            cruise = max(settings.MIN_CRUISE_POWER, int(round(cruise * scale)))

        left, right = compute_wheel_powers(
            heading_error_deg=error,
            cruise_power=cruise,
            steering_k=settings.STEERING_K,
            max_power=settings.MAX_MOTOR_POWER,
        )
        self._motor.set_desired(left, right)
        self._status.update(
            distance_to_target_m=round(dist, 2),
            bearing_to_target_deg=round(bearing, 1),
            heading_error_deg=round(error, 1),
            desired_left=left,
            desired_right=right,
        )
        return events

    # ------------------------------------------------------------------
    def _fault(self, reason: str, fatal: bool) -> None:
        mission_id = self.mission_id
        logger.error("Navigator fault: %s (fatal=%s) mission=%s", reason, fatal, mission_id)
        self.pause()
        with self._lock:
            self._hold_reason = reason
        if self.on_fault and mission_id:
            self._safe(self.on_fault, mission_id, reason, fatal)

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Navigator callback error: %s", exc)

    def _publish_state(self) -> None:
        if self._health:
            with self._lock:
                self._health.set_nav_state(self._state.value)
                self._health.set_mission(self._mission_id, self._index, len(self._waypoints))
