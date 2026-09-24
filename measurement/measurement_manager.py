"""
measurement/measurement_manager.py

THE central acquisition pipeline (spec section 38). Every STM32 combined
packet passes through here. This module is the single place where the
non-negotiable business rules (spec section 61, RULES 1-12) are enforced.

New STM32 <-> RPi5 architecture entry point: `on_stm32_packet(packet)`.
For every packet (0.5 Hz) it:
  1. Updates the GPS + compass state from `packet["gps"]` / `packet["compass"]`
  2. Publishes that position/heading to MQTT telemetry continuously, for
     real-time frontend visualization -- independent of motor state
  3. Updates motor state from `packet["motors"]["left"/"right"]`
     (left == 0 and right == 0 -> IDLE, otherwise -> MOVING; a missing/
     stale STM32 link naturally decays to UNKNOWN -- see
     hardware/motor_controller.py)
  4. If and only if motor state is IDLE, gates sensor SAMPLING to once
     every SENSOR_SAMPLE_INTERVAL_SECONDS (not on every 0.5 Hz packet)
     and, once due, feeds `packet["sensors"]` into the unchanged
     acceptance pipeline below via `on_sensor_packet`.

The acceptance pipeline itself (`on_sensor_packet` / `_process`) is
UNCHANGED from the previous architecture:
  1. Motor state check      -> reject if not confirmed IDLE
  2. GPS validity check     -> reject if no valid/recent fix
  3. Grid matching          -> reject if outside GRID_MATCH_RADIUS_METERS
  4. Sensor field validation -> invalid fields become NULL (not rejected)
  5. Session lookup/creation (reuse ACTIVE, never touch COMPLETED)
  6. Atomically: persist reading into the temporary SQLite upload
     buffer, update the running sum/count aggregation, bump
     sample_count, and -- if this is the final sample -- complete the
     session and persist its final averages (single SQLite transaction,
     see SQLiteManager.record_accepted_sample)
  7. Publish MQTT telemetry (best effort, never blocks/blocks nothing)

This module never talks to Supabase directly -- cloud upload is fully
decoupled and handled asynchronously by cloud/uploader.py.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from config.settings import settings
from hardware.motor_controller import MotorControllerWorker, MotorState
from hardware.gps import GPSWorker
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
    def __init__(self, *, sqlite_manager: SQLiteManager, gps_worker: GPSWorker,
                 motor_worker: MotorControllerWorker, grid_matcher: GridMatcher,
                 session_manager: SessionManager, sensor_validator: SensorValidator,
                 mqtt_client=None, health=None):
        self._db = sqlite_manager
        self._gps = gps_worker
        self._motor = motor_worker
        self._grids = grid_matcher
        self._sessions = session_manager
        self._validator = sensor_validator
        self._mqtt = mqtt_client
        self._health = health
        # Serializes processing of consecutive sensor packets. There is
        # normally only one caller (the STM32Worker thread), but this
        # guards against any future concurrent callers.
        self._lock = threading.Lock()
        # Sensor-sampling cadence gate (new architecture): the STM32
        # stream arrives at 0.5 Hz, but a persisted sample must only be
        # taken once every SENSOR_SAMPLE_INTERVAL_SECONDS while IDLE.
        # None means "no sample taken yet since motors last became
        # IDLE" -- the next qualifying packet samples immediately.
        self._next_sample_due_at: Optional[float] = None

    # ------------------------------------------------------------------
    # New architecture entry point: one combined STM32 packet per call.
    # ------------------------------------------------------------------
    def on_stm32_packet(self, packet: dict) -> None:
        with self._lock:
            self._process_stm32_packet(packet)

    def _process_stm32_packet(self, packet: dict) -> None:
        if not isinstance(packet, dict):
            return

        now = time.time()

        device_id = packet.get("device_id")
        if device_id and device_id != settings.DEVICE_ID:
            logger.warning(
                "STM32 packet device_id=%r does not match configured DEVICE_ID=%r",
                device_id, settings.DEVICE_ID,
            )

        # STEP: update GPS + compass state from this packet (spec
        # section 2). GPS freshness validation continues to be applied
        # on read, in hardware/gps.py::get_fix().
        gps_data = packet.get("gps")
        latitude = longitude = None
        if isinstance(gps_data, dict):
            latitude = _as_float(gps_data.get("latitude"))
            longitude = _as_float(gps_data.get("longitude"))

        compass_data = packet.get("compass")
        heading = _as_float(compass_data.get("heading")) if isinstance(compass_data, dict) else None

        if latitude is not None and longitude is not None:
            self._gps.update(latitude, longitude, heading, now)

        # STEP: continuously publish current GPS + heading to the
        # existing MQTT telemetry mechanism for real-time frontend
        # visualization -- independent of motor state / sensor sampling.
        self._publish_position_telemetry()

        # STEP: update motor state from motors.left/right (spec
        # section 3). left == 0 and right == 0 -> IDLE, else -> MOVING.
        # A missing/invalid motors object is never guessed at; it is
        # simply not applied, so freshness-based staleness will carry
        # the reported state to UNKNOWN if the STM32 link is unhealthy.
        motors = packet.get("motors")
        if isinstance(motors, dict) and "left" in motors and "right" in motors:
            self._motor.update(motors.get("left"), motors.get("right"), now)
        else:
            logger.warning("STM32 packet missing/invalid 'motors' object")

        motor_state = self._motor.get_state()
        if self._health:
            self._health.set_motor_state(motor_state.value)

        if motor_state != MotorState.IDLE:
            # MOVING or UNKNOWN -- never acquire sensor samples, and
            # reset the sampling cadence so the next IDLE period starts
            # a fresh "collect one sample every N seconds" cycle.
            self._next_sample_due_at = None
            return

        # STEP: sensor-sampling cadence gate. Only once every
        # SENSOR_SAMPLE_INTERVAL_SECONDS while IDLE do we even attempt
        # to acquire a sample -- NOT on every 0.5 Hz STM32 packet.
        if self._next_sample_due_at is not None and now < self._next_sample_due_at:
            return

        sensors = packet.get("sensors")
        if not isinstance(sensors, dict):
            logger.warning("STM32 packet missing/invalid 'sensors' object at a sampling instant")
            return

        # This sampling instant is consumed regardless of downstream
        # accept/reject outcome (grid/GPS validity etc.) -- the cadence
        # is about how often we *attempt* a sample while idle, matching
        # "collect exactly 1 sensor sample every 6 seconds".
        self._next_sample_due_at = now + settings.SENSOR_SAMPLE_INTERVAL_SECONDS
        self._process(sensors, None)

    def _publish_position_telemetry(self) -> None:
        if not self._mqtt:
            return
        fix = self._gps.get_fix()
        self._mqtt.publish("telemetry/position", {
            "latitude": fix.latitude,
            "longitude": fix.longitude,
            "heading": fix.heading,
            "gps_valid": fix.valid,
            "age_seconds": round(fix.age_seconds, 2) if fix.age_seconds != float("inf") else None,
            "ts": _now_iso(),
        })

    # ------------------------------------------------------------------
    # Acceptance pipeline (unchanged business logic). `mode` is retained
    # only for backward-compatible call signatures/tests -- it is never
    # used in the acceptance decision, exactly as before.
    # ------------------------------------------------------------------
    def on_sensor_packet(self, sensors: dict, mode: Optional[str] = None) -> None:
        with self._lock:
            self._process(sensors, mode)

    # ------------------------------------------------------------------
    def _reject(self, reason: str, **context) -> None:
        logger.warning("Sensor packet rejected: %s %s", reason, context)
        if self._mqtt:
            self._mqtt.publish("sensor/rejected", {"reason": reason, **context, "ts": _now_iso()})

    def _process(self, sensors: dict, mode: Optional[str]) -> None:
        # STEP: motor state check (RULES 1/2) -- authoritative safety gate.
        motor_state = self._motor.get_state()
        if self._health:
            self._health.set_motor_state(motor_state.value)
        if motor_state != MotorState.IDLE:
            self._reject("motor_not_idle", motor_state=motor_state.value)
            return

        # STEP: GPS validity + freshness (RULE 3).
        fix = self._gps.get_fix()
        if not fix.valid or fix.latitude is None or fix.longitude is None:
            self._reject("gps_invalid_or_stale", age_seconds=round(fix.age_seconds, 2)
                          if fix.age_seconds != float("inf") else None)
            return

        # STEP: grid matching (RULE 4).
        grid = self._grids.find_matching_grid(fix.latitude, fix.longitude)
        if grid is None:
            self._reject("outside_grid_radius", latitude=fix.latitude, longitude=fix.longitude)
            return

        # STEP: sensor field validation (RULE 5). Only rejects if the
        # entire packet is unusable; individual bad fields become None.
        validated = self._validator.validate(sensors)
        if validated is None:
            self._reject("invalid_sensor_packet", raw=sensors)
            return

        # STEP: session lookup/creation (RULES 6-10).
        session = self._sessions.get_or_create_active_session(
            grid, settings.DEVICE_ID, fix.latitude, fix.longitude
        )
        if session["sample_count"] >= settings.MAX_READINGS_PER_GRID or session["status"] != "ACTIVE":
            # Defensive guard only -- should not normally happen since
            # get_or_create_active_session never returns a full/completed
            # session. Protects against any future race.
            self._reject("session_full_race_guard", session_id=session["session_id"])
            return

        recorded_at = _now_iso()

        # STEP: persist reading into the temporary upload buffer, update
        # the running sum/count aggregation, bump sample_count, and (if
        # this is the final sample) complete the session and persist its
        # final averages -- ALL inside a single atomic SQLite
        # transaction. Either every one of these writes commits or none
        # do, so a crash/power-loss can never leave sample_count out of
        # sync with the readings that back it.
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

        # STEP: the final average (RULES 11, 24-25) was already computed
        # from the running sum/count aggregation and persisted to
        # local_averages as part of the same atomic transaction above.
        if updated_session["status"] == "COMPLETED":
            logger.info("Local average stored for session %s: %s", session["session_id"], averages)
            if self._mqtt:
                self._mqtt.publish("session/completed", {
                    "grid_code": grid.get("grid_code"),
                    "grid_id": grid["grid_id"],
                    "session_id": session["session_id"],
                    "sample_count": updated_session["sample_count"],
                    "ts": _now_iso(),
                })
