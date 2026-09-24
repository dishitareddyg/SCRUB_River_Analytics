"""
tests/test_stm32_integration.py

Tests for the new STM32 <-> RPi5 combined-packet architecture:

  - hardware/stm32.py: parsing/framing of the new combined JSON packet
    (device_id, timestamp, motors, gps, compass, sensors), and the
    disconnect notification hook.
  - hardware/gps.py: GPS + compass state update/read with age-based
    validity (fed by packets rather than a dedicated serial thread).
  - measurement/measurement_manager.py::on_stm32_packet:
      * continuous GPS+heading telemetry publishing, independent of
        motor state
      * motor state derived from motors.left/right
      * sensor sampling gated to once every SENSOR_SAMPLE_INTERVAL_SECONDS
        while IDLE (not on every 0.5 Hz packet), resetting when motors
        leave IDLE
      * STM32 disconnect forces motor state to UNKNOWN immediately

Run with:
    pytest tests/test_stm32_integration.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from hardware.gps import GPSWorker
from hardware.motor_controller import MotorControllerWorker, MotorState
from hardware.stm32 import STM32Worker
from measurement.grid_matcher import GridMatcher
from measurement.measurement_manager import MeasurementManager
from measurement.sensor_validator import SensorValidator
from measurement.session_manager import SessionManager
from storage.sqlite_manager import SQLiteManager

VALID_STM32_LINE = (
    '{"device_id": "BOT001", "timestamp": "2026-01-01T00:00:00Z", '
    '"motors": {"left": 0, "right": 0}, '
    '"gps": {"latitude": 12.123456, "longitude": 77.123456}, '
    '"compass": {"heading": 182.4}, '
    '"sensors": {"ph": 7.12, "tds": 214.2, "turbidity": 15.3, '
    '"temperature_c": 27.4, "humidity_percent": 71.2}}'
)


class FakeMQTT:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        self.messages.append((topic, payload))


# ---------------------------------------------------------------- STM32Worker
def test_stm32_valid_packet_calls_callback_with_full_dict():
    received = []
    worker = STM32Worker(on_packet=received.append)
    worker._handle_line(VALID_STM32_LINE)
    assert len(received) == 1
    packet = received[0]
    assert packet["device_id"] == "BOT001"
    assert packet["motors"] == {"left": 0, "right": 0}
    assert packet["gps"]["latitude"] == 12.123456
    assert packet["compass"]["heading"] == 182.4
    assert packet["sensors"]["ph"] == 7.12


def test_stm32_malformed_json_discarded_silently():
    received = []
    worker = STM32Worker(on_packet=received.append)
    worker._handle_line("{not valid json")
    assert received == []


def test_stm32_non_object_json_discarded():
    received = []
    worker = STM32Worker(on_packet=received.append)
    worker._handle_line("[1, 2, 3]")
    worker._handle_line('"just a string"')
    assert received == []


def test_stm32_callback_exception_never_propagates():
    def bad_callback(_packet):
        raise RuntimeError("boom")

    worker = STM32Worker(on_packet=bad_callback)
    # Must not raise.
    worker._handle_line(VALID_STM32_LINE)


def test_stm32_notify_disconnect_invokes_hook():
    calls = []
    worker = STM32Worker(on_packet=lambda p: None, on_disconnect=lambda: calls.append(True))
    worker._notify_disconnect()
    assert calls == [True]


# ---------------------------------------------------------------- GPSWorker
def test_gps_update_and_get_fix_reports_heading():
    gps = GPSWorker()
    gps.update(12.9, 77.5, heading=90.0, ts=1000.0)
    fix = gps.get_fix()
    assert fix.latitude == 12.9
    assert fix.longitude == 77.5
    assert fix.heading == 90.0


def test_gps_no_data_is_invalid():
    gps = GPSWorker()
    fix = gps.get_fix()
    assert fix.valid is False
    assert fix.latitude is None


def test_gps_becomes_invalid_after_max_age():
    from config.settings import settings
    original = settings.GPS_MAX_AGE_SECONDS
    object.__setattr__(settings, "GPS_MAX_AGE_SECONDS", 0.05)
    try:
        gps = GPSWorker()
        gps.update(12.9, 77.5, heading=90.0)
        assert gps.get_fix().valid is True
        import time
        time.sleep(0.1)
        assert gps.get_fix().valid is False
    finally:
        object.__setattr__(settings, "GPS_MAX_AGE_SECONDS", original)


def test_gps_update_ignores_missing_lat_or_lon():
    gps = GPSWorker()
    gps.update(None, 77.5)
    assert gps.get_fix().valid is False


# ---------------------------------------------------------------- MeasurementManager.on_stm32_packet
def _bare_manager(mqtt):
    """A MeasurementManager with no DB/grid/session wiring -- only valid
    for scenarios that never reach the sensor-acceptance pipeline (e.g.
    motors MOVING), since telemetry publishing must work independently
    of the rest of the pipeline."""
    gps = GPSWorker()
    motor = MotorControllerWorker()
    mgr = MeasurementManager(
        sqlite_manager=None, gps_worker=gps, motor_worker=motor,
        grid_matcher=None, session_manager=None, sensor_validator=None,
        mqtt_client=mqtt, health=None,
    )
    return mgr, gps, motor


def test_telemetry_published_every_packet_even_while_moving():
    mqtt = FakeMQTT()
    mgr, gps, motor = _bare_manager(mqtt)
    packet = {
        "device_id": "BOT001",
        "motors": {"left": 100, "right": 100},  # MOVING
        "gps": {"latitude": 12.9, "longitude": 77.5},
        "compass": {"heading": 45.0},
        "sensors": {"ph": 7.0},
    }
    mgr.on_stm32_packet(packet)

    topics = [t for t, _ in mqtt.messages]
    assert "telemetry/position" in topics
    payload = dict(mqtt.messages[topics.index("telemetry/position")][1])
    assert payload["latitude"] == 12.9
    assert payload["longitude"] == 77.5
    assert payload["heading"] == 45.0
    assert payload["gps_valid"] is True
    # Motors moving -> no sensor sample may be taken (safety rule).
    assert motor.get_state() == MotorState.MOVING


def test_missing_motors_object_does_not_crash_and_skips_sampling():
    mqtt = FakeMQTT()
    mgr, gps, motor = _bare_manager(mqtt)
    packet = {
        "gps": {"latitude": 12.9, "longitude": 77.5},
        "compass": {"heading": 45.0},
        "sensors": {"ph": 7.0},
    }
    mgr.on_stm32_packet(packet)  # must not raise
    # No motors data ever recorded -> UNKNOWN -> never assume idle.
    assert motor.get_state() == MotorState.UNKNOWN


GRID_KNG001 = {
    "grid_id": "grid-kng001",
    "lake_id": "lake-1",
    "grid_code": "KNG001",
    "grid_size_m": 5,
    "center_lat": 12.9000,
    "center_lon": 77.5000,
}


def _full_manager(tmp_path, mqtt):
    """A fully wired MeasurementManager (real SQLite/grid/session/
    validator) for exercising the end-to-end sampling cadence."""
    db = SQLiteManager(str(tmp_path / "test.db"))
    db.replace_grid_cache([GRID_KNG001])
    grid_matcher = GridMatcher(db)
    session_manager = SessionManager(db)
    validator = SensorValidator()
    gps = GPSWorker()
    motor = MotorControllerWorker()
    mgr = MeasurementManager(
        sqlite_manager=db, gps_worker=gps, motor_worker=motor,
        grid_matcher=grid_matcher, session_manager=session_manager,
        sensor_validator=validator, mqtt_client=mqtt, health=None,
    )
    return mgr, db, gps, motor


def _packet(now_iso="t", left=0, right=0):
    return {
        "device_id": "BOT001",
        "timestamp": now_iso,
        "motors": {"left": left, "right": right},
        "gps": {"latitude": GRID_KNG001["center_lat"], "longitude": GRID_KNG001["center_lon"]},
        "compass": {"heading": 10.0},
        "sensors": {"ph": 7.1, "tds": 200.0, "turbidity": 10.0,
                    "temperature_c": 25.0, "humidity_percent": 60.0},
    }


def test_sensor_sample_gated_to_once_every_6_seconds_while_idle(tmp_path, monkeypatch):
    mqtt = FakeMQTT()
    mgr, db, gps, motor = _full_manager(tmp_path, mqtt)

    fake_now = [1000.0]
    monkeypatch.setattr("measurement.measurement_manager.time.time", lambda: fake_now[0])

    # t=1000: first IDLE packet -> samples immediately (no prior sample).
    mgr.on_stm32_packet(_packet())
    assert db.count_pending_uploads() == 1

    # t=1002, t=1004: still within the 6s cadence -> no additional sample.
    fake_now[0] = 1002.0
    mgr.on_stm32_packet(_packet())
    assert db.count_pending_uploads() == 1

    fake_now[0] = 1004.0
    mgr.on_stm32_packet(_packet())
    assert db.count_pending_uploads() == 1

    # t=1006: exactly one SENSOR_SAMPLE_INTERVAL_SECONDS later -> samples again.
    fake_now[0] = 1006.0
    mgr.on_stm32_packet(_packet())
    assert db.count_pending_uploads() == 2

    db.close()


def test_sampling_cadence_resets_when_motors_leave_idle(tmp_path, monkeypatch):
    mqtt = FakeMQTT()
    mgr, db, gps, motor = _full_manager(tmp_path, mqtt)

    fake_now = [2000.0]
    monkeypatch.setattr("measurement.measurement_manager.time.time", lambda: fake_now[0])

    # First sample while idle.
    mgr.on_stm32_packet(_packet(left=0, right=0))
    assert db.count_pending_uploads() == 1

    # Motors start moving shortly after -- no sample, cadence resets.
    fake_now[0] = 2001.0
    mgr.on_stm32_packet(_packet(left=100, right=100))
    assert db.count_pending_uploads() == 1
    assert motor.get_state() == MotorState.MOVING

    # Motors become idle again well before a full 6s has elapsed since
    # the first sample -- because the cadence reset on leaving IDLE, the
    # very next idle packet samples immediately rather than waiting out
    # the original 6s window.
    fake_now[0] = 2002.0
    mgr.on_stm32_packet(_packet(left=0, right=0))
    assert db.count_pending_uploads() == 2

    db.close()


def test_no_sampling_while_moving_or_unknown(tmp_path, monkeypatch):
    mqtt = FakeMQTT()
    mgr, db, gps, motor = _full_manager(tmp_path, mqtt)

    fake_now = [3000.0]
    monkeypatch.setattr("measurement.measurement_manager.time.time", lambda: fake_now[0])

    mgr.on_stm32_packet(_packet(left=50, right=50))
    assert db.count_pending_uploads() == 0
    assert motor.get_state() == MotorState.MOVING

    # Missing motors object -> UNKNOWN -> still no sample.
    fake_now[0] = 3001.0
    packet = _packet()
    del packet["motors"]
    mgr.on_stm32_packet(packet)
    assert db.count_pending_uploads() == 0

    db.close()


# ---------------------------------------------------------------- disconnect wiring
def test_stm32_disconnect_hook_forces_motor_unknown():
    motor = MotorControllerWorker()
    motor.update(0, 0)
    assert motor.get_state() == MotorState.IDLE

    worker = STM32Worker(on_packet=lambda p: None, on_disconnect=motor.force_unknown)
    worker._notify_disconnect()

    assert motor.get_state() == MotorState.UNKNOWN
