"""
tests/test_acceptance.py

End-to-end acceptance tests for MeasurementManager, covering the scenarios
from the project spec's acceptance-test matrix (TEST1, TEST2, TEST3, TEST4,
TEST5, TEST6, TEST7). Hardware (GPS/motor) is faked; SQLite is real
(a temp file per test) so the full session/sample-numbering/completion
logic is exercised for real.

Run with:
    pytest tests/test_acceptance.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from hardware.motor_controller import MotorState
from measurement.grid_matcher import GridMatcher
from measurement.measurement_manager import MeasurementManager
from measurement.sensor_validator import SensorValidator
from measurement.session_manager import SessionManager
from storage.sqlite_manager import SQLiteManager

GRID_KNG001 = {
    "grid_id": "grid-kng001",
    "lake_id": "lake-1",
    "grid_code": "KNG001",
    "grid_size_m": 5,
    "center_lat": 12.9000,
    "center_lon": 77.5000,
}

# New STM32 <-> RPi5 combined packet: sensor fields use the same names
# as the internal/DB fields directly.
VALID_PACKET = {"ph": 7.12, "tds": 214.2, "turbidity": 15.3, "temperature_c": 27.4, "humidity_percent": 71.2}


class FakeGPS:
    """Duck-typed stand-in for hardware.gps.GPSWorker."""

    def __init__(self):
        self.latitude = GRID_KNG001["center_lat"]
        self.longitude = GRID_KNG001["center_lon"]
        self.valid = True
        self.age_seconds = 0.5

    def get_fix(self):
        from hardware.gps import GPSFix
        return GPSFix(latitude=self.latitude, longitude=self.longitude,
                      valid=self.valid, age_seconds=self.age_seconds, timestamp=0)


class FakeMotor:
    """Duck-typed stand-in for hardware.motor_controller.MotorControllerWorker."""

    def __init__(self, state: MotorState = MotorState.IDLE):
        self.state = state

    def get_state(self):
        return self.state


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.db")
        manager = SQLiteManager(path)
        manager.replace_grid_cache([GRID_KNG001])
        yield manager
        manager.close()


def make_manager(db, gps, motor):
    grid_matcher = GridMatcher(db)
    session_manager = SessionManager(db)
    validator = SensorValidator()
    return MeasurementManager(
        sqlite_manager=db, gps_worker=gps, motor_worker=motor,
        grid_matcher=grid_matcher, session_manager=session_manager,
        sensor_validator=validator, mqtt_client=None, health=None,
    )


# TEST 1: motor moving + valid GPS + valid packet -> nothing stored
def test_motor_moving_rejects(db):
    gps = FakeGPS()
    motor = FakeMotor(MotorState.MOVING)
    mgr = make_manager(db, gps, motor)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    assert db.count_pending_uploads() == 0
    assert db.get_active_session(GRID_KNG001["grid_id"]) is None


# TEST 2: motor idle + invalid GPS -> nothing stored
def test_invalid_gps_rejects(db):
    gps = FakeGPS()
    gps.valid = False
    motor = FakeMotor(MotorState.IDLE)
    mgr = make_manager(db, gps, motor)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    assert db.count_pending_uploads() == 0


# Motor UNKNOWN must also reject (never assume idle on lost comms)
def test_motor_unknown_rejects(db):
    gps = FakeGPS()
    motor = FakeMotor(MotorState.UNKNOWN)
    mgr = make_manager(db, gps, motor)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    assert db.count_pending_uploads() == 0


# TEST 3: motor idle + valid GPS but ~20m from grid center -> nothing stored
def test_gps_outside_radius_rejects(db):
    gps = FakeGPS()
    gps.latitude = GRID_KNG001["center_lat"] + 0.00018  # ~20m north
    motor = FakeMotor(MotorState.IDLE)
    mgr = make_manager(db, gps, motor)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    assert db.count_pending_uploads() == 0


# TEST 4: motor idle + valid GPS ~3m from grid -> accepted
def test_gps_within_radius_accepts(db):
    gps = FakeGPS()
    gps.latitude = GRID_KNG001["center_lat"] + 0.000027  # ~3m north
    motor = FakeMotor(MotorState.IDLE)
    mgr = make_manager(db, gps, motor)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    assert db.count_pending_uploads() == 1
    session = db.get_active_session(GRID_KNG001["grid_id"])
    assert session is not None
    assert session["sample_count"] == 1


# TEST 5 & 6: 10 readings complete a session; the 11th creates a NEW session
def test_session_completes_and_revisit_creates_new_session(db):
    gps = FakeGPS()
    motor = FakeMotor(MotorState.IDLE)
    mgr = make_manager(db, gps, motor)

    for _ in range(10):
        mgr.on_sensor_packet(VALID_PACKET, "MANUAL")

    session_a = db.get_active_session(GRID_KNG001["grid_id"])
    assert session_a is None  # no longer ACTIVE -- it's COMPLETED

    with db._cursor() as cur:  # test-only introspection
        cur.execute("SELECT * FROM local_sessions")
        rows = [dict(r) for r in cur.fetchall()]
    assert len(rows) == 1
    assert rows[0]["status"] == "COMPLETED"
    assert rows[0]["sample_count"] == 10
    session_a_id = rows[0]["session_id"]

    # Local average must have been computed for the completed session
    avg = db.get_local_average(GRID_KNG001["grid_id"], session_a_id)
    assert avg is not None
    assert avg["sample_count"] == 10

    # Revisit: next accepted sample must start a brand new session (TEST 6)
    mgr.on_sensor_packet(VALID_PACKET, "MANUAL")
    with db._cursor() as cur:
        cur.execute("SELECT * FROM local_sessions ORDER BY started_at")
        rows = [dict(r) for r in cur.fetchall()]
    assert len(rows) == 2
    session_b = rows[1]
    assert session_b["session_id"] != session_a_id
    assert session_b["sample_count"] == 1

    # Session A must remain completely unchanged
    session_a_after = [r for r in rows if r["session_id"] == session_a_id][0]
    assert session_a_after["sample_count"] == 10
    assert session_a_after["status"] == "COMPLETED"


# TEST 7: one invalid field -> that field NULL, others preserved, sample still accepted
def test_partial_invalid_packet_still_accepted_with_nulls(db):
    gps = FakeGPS()
    motor = FakeMotor(MotorState.IDLE)
    mgr = make_manager(db, gps, motor)

    packet = {"ph": 7.12, "tds": "N/A", "turbidity": 15.3, "temperature_c": 27.4, "humidity_percent": 71.2}
    mgr.on_sensor_packet(packet, "MANUAL")

    session = db.get_active_session(GRID_KNG001["grid_id"])
    readings = db.get_readings_for_session(session["session_id"])
    assert len(readings) == 1
    assert readings[0]["ph"] == 7.12
    assert readings[0]["tds"] is None
    assert readings[0]["turbidity"] == 15.3
