"""
measurement/measurement_manager.py

Central acquisition pipeline — IDENTICAL business logic to SCRUB_River_Analytics,
with one addition: integration with the Navigator's collection handoff.

Every STM32 combined packet flows through on_stm32_packet():
  1. Update GPS + compass state.
  2. Publish position to MQTT (always, every packet).
  3. Update motor state from motors.left/right.
  4. If state is COLLECTING (Navigator said "we arrived"):
       - Apply sensor-sampling cadence gate (one sample every
         SENSOR_SAMPLE_INTERVAL_SECONDS, not on every 0.5 Hz packet).
       - Feed sensors into the unchanged acceptance pipeline.
       - When the session reaches MAX_READINGS_PER_GRID, call
         navigator.on_grid_collection_complete().
  5. If motor state is MOVING or UNKNOWN → reject sensor sample
     (same SCRUB safety gate).

The acceptance pipeline (_process) is UNCHANGED from SCRUB:
  motor gate → GPS gate → grid match → sensor validation →
  session get-or-create → atomic SQLite write → MQTT publish.

This module never talks to Supabase directly.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from config.settings import settings
from hardware.gps import GPSWorker
from hardware.motor_controller import MotorControllerWorker, MotorState
from measurement.grid_matcher import GridMatcher
from measurement.sensor_validator import SensorValidator
from measurement.session_manager import SessionManager
from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _as_float(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class MeasurementManager:
    def __init__(
        self,
        *,
        sqlite_manager: SQLiteManager,
        gps_worker: GPSWorker,
        motor_worker: MotorControllerWorker,
        grid_matcher: GridMatcher,
        session_manager: SessionManager,
        sensor_validator: SensorValidator,
        navigator,                    # Navigator — for on_grid_collection_complete()
        mission_manager=None,         # MissionManager — for on_grid_session_complete()
        mqtt_client=None,
        health=None,
    ) -> None:
        self._db = sqlite_manager
        self._gps = gps_worker
        self._motor = motor_worker
        self._grids = grid_matcher
        self._sessions = session_manager
        self._validator = sensor_validator
        self._nav = navigator
        self._mission_mgr = mission_manager
        self._mqtt = mqtt_client
        self._health = health

        self._lock = threading.Lock()

        # Sensor-sampling cadence gate (same as SCRUB).
        # None → "first sample may be taken immediately when IDLE at grid."
        self._next_sample_due_at: Optional[float] = None

        # Track the current grid being collected so we know when to signal done.
        self._collecting_grid: Optional[dict] = None
        self._collecting = threading.Event()

    # ------------------------------------------------------------------
    # Called by Navigator when the bot arrives at a grid.
    # ------------------------------------------------------------------
    def on_grid_arrived(self, grid_waypoint: dict) -> None:
        """
        Navigator signals arrival at grid_waypoint.
        We latch the grid and reset the cadence timer so the first sample
        fires on the next eligible STM32 packet.
        """
        with self._lock:
            self._collecting_grid = grid_waypoint
            self._next_sample_due_at = None   # first sample immediately
        logger.info(
            "Measurement: now COLLECTING at grid %s",
            grid_waypoint.get("grid_code", grid_waypoint.get("grid_id")),
        )

    # ------------------------------------------------------------------
    # Primary entry point: one STM32 combined packet per call.
    # ------------------------------------------------------------------
    def on_stm32_packet(self, packet: dict) -> None:
        with self._lock:
            self._process_stm32_packet(packet)

    def _process_stm32_packet(self, packet: dict) -> None:
        if not isinstance(packet, dict):
            return

        now = time.time()

        # STEP 1: update GPS + compass state.
        gps_data = packet.get("gps")
        latitude = longitude = None
        if isinstance(gps_data, dict):
            latitude = _as_float(gps_data.get("latitude"))
            longitude = _as_float(gps_data.get("longitude"))

        compass_data = packet.get("compass")
        heading = (
            _as_float(compass_data.get("heading"))
            if isinstance(compass_data, dict) else None
        )

        if latitude is not None and longitude is not None:
            self._gps.update(latitude, longitude, heading, now)

        # STEP 2: always publish position to MQTT.
        self._publish_position_telemetry()

        # STEP 3: update motor state.
        motors = packet.get("motors")
        if isinstance(motors, dict) and "left" in motors and "right" in motors:
            self._motor.update(motors["left"], motors["right"], now)
        else:
            logger.warning("STM32 packet missing/invalid 'motors' object")

        motor_state = self._motor.get_state()
        if self._health:
            self._health.set_motor_state(motor_state.value)

        # STEP 4: only attempt sensor sampling if Navigator is COLLECTING
        # (arrived at a grid) and motors are confirmed IDLE.
        if self._collecting_grid is None:
            return   # Navigator hasn't told us to collect yet.

        if motor_state != MotorState.IDLE:
            # Motors still spinning down — reset cadence and wait.
            self._next_sample_due_at = None
            return

        # Sensor-sampling cadence gate.
        if self._next_sample_due_at is not None and now < self._next_sample_due_at:
            return

        sensors = packet.get("sensors")
        if not isinstance(sensors, dict):
            logger.warning("STM32 packet missing 'sensors' at a sampling instant")
            return

        self._next_sample_due_at = now + settings.SENSOR_SAMPLE_INTERVAL_SECONDS
        self._process(sensors, grid_hint=self._collecting_grid)

    # ------------------------------------------------------------------
    # Acceptance pipeline (UNCHANGED from SCRUB — see SCRUB docs).
    # ------------------------------------------------------------------
    def _reject(self, reason: str, **context) -> None:
        logger.warning("Sensor packet rejected: %s %s", reason, context)
        if self._mqtt:
            self._mqtt.publish("sensor/rejected", {"reason": reason, **context, "ts": _now_iso()})

    def _process(self, sensors: dict, grid_hint: Optional[dict] = None) -> None:
        # Motor state check (authoritative safety gate).
        motor_state = self._motor.get_state()
        if motor_state != MotorState.IDLE:
            self._reject("motor_not_idle", motor_state=motor_state.value)
            return

        # GPS validity + freshness.
        fix = self._gps.get_fix()
        if not fix.valid or fix.latitude is None or fix.longitude is None:
            self._reject(
                "gps_invalid_or_stale",
                age_seconds=round(fix.age_seconds, 2)
                if fix.age_seconds != float("inf") else None,
            )
            return

        # Grid matching.
        grid = self._grids.find_matching_grid(fix.latitude, fix.longitude)
        if grid is None:
            self._reject("outside_grid_radius",
                         latitude=fix.latitude, longitude=fix.longitude)
            return

        # Sensor field validation.
        validated = self._validator.validate(sensors)
        if validated is None:
            self._reject("invalid_sensor_packet", raw=sensors)
            return

        # Session lookup / creation.
        session = self._sessions.get_or_create_active_session(
            grid, settings.DEVICE_ID, fix.latitude, fix.longitude
        )
        if (
            session["sample_count"] >= settings.MAX_READINGS_PER_GRID
            or session["status"] != "ACTIVE"
        ):
            self._reject("session_full_race_guard", session_id=session["session_id"])
            return

        recorded_at = _now_iso()

        # Atomic SQLite transaction: insert reading, update running sums,
        # bump sample_count, (if final) complete session + persist averages.
        result = self._db.record_accepted_sample(
            session_id=session["session_id"],
            grid_id=grid["grid_id"],
            device_id=settings.DEVICE_ID,
            recorded_at=recorded_at,
            latitude=fix.latitude,
            longitude=fix.longitude,
            ph=validated["ph"],
            tds=validated["tds"],
            turbidity=validated["turbidity"],
            temperature_c=validated["temperature_c"],
            humidity_percent=validated["humidity_percent"],
            max_readings=settings.MAX_READINGS_PER_GRID,
        )
        updated_session = result["session"]
        sample_number = result["sample_number"]
        averages = result["averages"]

        logger.info(
            "Accepted sample %d/%d for grid %s (session %s)",
            sample_number, settings.MAX_READINGS_PER_GRID,
            grid.get("grid_code", grid["grid_id"]), session["session_id"],
        )
        if self._mqtt:
            self._mqtt.publish("sensor/accepted", {
                "grid_code": grid.get("grid_code"),
                "grid_id": grid["grid_id"],
                "session_id": session["session_id"],
                "sample_number": sample_number,
                "sample_count": updated_session["sample_count"],
                "max_readings": settings.MAX_READINGS_PER_GRID,
                "latitude": fix.latitude,
                "longitude": fix.longitude,
                "ts": recorded_at,
            })

        # If session completed → signal Navigator and MissionManager.
        if updated_session["status"] == "COMPLETED":
            logger.info(
                "Grid session %s COMPLETED (%d samples). Averages: %s",
                session["session_id"], updated_session["sample_count"], averages,
            )
            if self._mqtt:
                self._mqtt.publish("session/completed", {
                    "grid_code": grid.get("grid_code"),
                    "grid_id": grid["grid_id"],
                    "session_id": session["session_id"],
                    "sample_count": updated_session["sample_count"],
                    "ts": _now_iso(),
                })
            # Notify MissionManager so it can update Supabase mission_grids.
            if self._mission_mgr:
                try:
                    self._mission_mgr.on_grid_session_complete(
                        grid["grid_id"], session["session_id"]
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("MissionManager notification error: %s", exc)

            # Clear collecting state so we don't keep sampling this grid.
            self._collecting_grid = None
            self._next_sample_due_at = None

            # Tell Navigator to move on.
            self._nav.on_grid_collection_complete()

    # ------------------------------------------------------------------
    def _publish_position_telemetry(self) -> None:
        if not self._mqtt:
            return
        fix = self._gps.get_fix()
        nav_state = self._nav.state.value if self._nav else "UNKNOWN"
        wp = self._nav.current_waypoint if self._nav else None
        self._mqtt.publish("telemetry/position", {
            "latitude": fix.latitude,
            "longitude": fix.longitude,
            "heading": fix.heading,
            "gps_valid": fix.valid,
            "age_seconds": round(fix.age_seconds, 2)
            if fix.age_seconds != float("inf") else None,
            "nav_state": nav_state,
            "target_grid": wp.get("grid_code") if wp else None,
            "ts": _now_iso(),
        })
