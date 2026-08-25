"""
tests/test_arduino_link.py — Unit tests for arduino_link.py parsing/robustness.

Tests: JSON parsing, malformed input, sensor key handling, SimulatedArduinoLink,
DualArduinoLink merge behavior, staleness detection.
"""

import json
import time

import pytest

from arduino_link import (
    ArduinoLink,
    ArduinoState,
    SensorGpsLink,
    MotorRcLink,
    DualArduinoLink,
    SimulatedArduinoLink,
)


# ─── ArduinoState defaults ────────────────────────────────────────────

def test_arduino_state_defaults():
    state = ArduinoState()
    assert state.gps_lat == 0.0
    assert state.mode == "MANUAL"
    assert state.sensors == {}
    assert state.timestamp == 0.0


# ─── ArduinoLink parsing ─────────────────────────────────────────────

def test_parse_valid_line():
    link = ArduinoLink.__new__(ArduinoLink)
    link._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()

    obj = {
        "seq": 42,
        "gps": {"lat": 12.91686, "lon": 77.48698, "alt": 840.0, "spd": 0.5, "course": 180.0, "sats": 8, "fix": 1},
        "hdg": 181.0,
        "sensors": {"ph": 7.3, "tds": 412.5, "turb": 18.2, "wtemp": 26.1, "atemp": 31.4, "hum": 68.2},
        "mode": "AUTO",
        "rc": {"ch1": 1500, "ch2": 1500},
    }
    link._parse_line(json.dumps(obj))

    state = link.get_latest_state()
    assert state.seq == 42
    assert state.gps_lat == 12.91686
    assert state.gps_lon == 77.48698
    assert state.heading == 181.0
    assert state.sensors["ph"] == 7.3
    assert state.mode == "AUTO"


def test_parse_malformed_json_does_not_crash():
    link = ArduinoLink.__new__(ArduinoLink)
    link._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()

    link._parse_line("{invalid json!!!")
    link._parse_line("")
    link._parse_line("not json at all")

    # Should not crash; _latest should remain unchanged
    state = link.get_latest_state()
    assert isinstance(state, ArduinoState)


def test_parse_missing_keys_uses_defaults():
    link = ArduinoLink.__new__(ArduinoLink)
    link._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()

    link._parse_line('{"seq": 1}')

    state = link.get_latest_state()
    assert state.seq == 1
    assert state.gps_lat == 0.0
    assert state.mode == "MANUAL"
    assert "ph" in state.sensors


def test_parse_empty_gps_object():
    link = ArduinoLink.__new__(ArduinoLink)
    link._sensor_keys = ["ph", "tds"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()

    link._parse_line('{"seq": 5, "gps": {}, "sensors": {"ph": 6.5}}')

    state = link.get_latest_state()
    assert state.seq == 5
    assert state.sensors["ph"] == 6.5
    assert state.sensors.get("tds", 0.0) == 0.0  # missing key gets 0.0


# ─── SimulatedArduinoLink ────────────────────────────────────────────

def test_simulated_generates_valid_state():
    sim = SimulatedArduinoLink()
    sim.open()
    state = sim.get_latest_state()

    assert state.gps_fix == 1
    assert state.gps_sats == 8
    assert state.mode in ("AUTO", "MANUAL")
    assert "ph" in state.sensors
    assert state.seq == 1


def test_simulated_increments_seq():
    sim = SimulatedArduinoLink()
    sim.open()
    s1 = sim.get_latest_state()
    s2 = sim.get_latest_state()
    s3 = sim.get_latest_state()

    assert s1.seq < s2.seq < s3.seq


def test_simulated_close_does_not_crash():
    sim = SimulatedArduinoLink()
    sim.open()
    sim.close()


# ─── send_motor_command / send_ping ───────────────────────────────────

def test_send_motor_command_clamps():
    link = ArduinoLink.__new__(ArduinoLink)
    link._serial = _FakeSerialForWrite()
    link.send_motor_command(200, -200)
    sent = json.loads(link._serial.last_written)
    assert sent["l"] == 100
    assert sent["r"] == -100


def test_send_ping():
    link = ArduinoLink.__new__(ArduinoLink)
    link._serial = _FakeSerialForWrite()
    link.send_ping()
    sent = json.loads(link._serial.last_written)
    assert sent["cmd"] == "ping"


class _FakeSerialForWrite:
    def __init__(self):
        self.is_open = True
        self.last_written = ""
    def write(self, data):
        self.last_written = data.decode("ascii").strip()
    def close(self):
        self.is_open = False


# ─── SensorGpsLink parsing ──────────────────────────────────────────

def test_sensor_gps_link_parse_valid_line():
    link = SensorGpsLink.__new__(SensorGpsLink)
    link._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()
    link._last_valid_time = 0.0
    link._was_fresh = True
    link._staleness_timeout_s = 3.0

    obj = {
        "seq": 10,
        "gps": {"lat": 12.92, "lon": 77.49, "alt": 840.0, "spd": 0.5, "course": 90.0, "sats": 10, "fix": 2},
        "hdg": 91.5,
        "sensors": {"ph": 7.0, "tds": 300.0, "turb": 10.0, "wtemp": 25.0, "atemp": 30.0, "hum": 60.0},
    }
    link._parse_line(json.dumps(obj))

    state = link.get_latest_state()
    assert state.gps_lat == 12.92
    assert state.heading == 91.5
    assert state.sensors["ph"] == 7.0
    assert state.gps_fix == 2
    assert not link.is_stale()


def test_sensor_gps_link_ignores_motor_fields():
    link = SensorGpsLink.__new__(SensorGpsLink)
    link._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    link._latest = ArduinoState()
    link._lock = __import__("threading").Lock()
    link._last_valid_time = 0.0
    link._was_fresh = True
    link._staleness_timeout_s = 3.0

    # SensorGpsLink should not crash on motor fields, just ignore them
    obj = {"seq": 1, "gps": {"lat": 1.0, "fix": 1}, "hdg": 45.0, "sensors": {}, "mode": "AUTO", "rc": {"ch1": 1500}}
    link._parse_line(json.dumps(obj))
    state = link.get_latest_state()
    assert state.gps_lat == 1.0
    assert state.mode == "MANUAL"  # default, not from parsed packet


# ─── MotorRcLink parsing ───────────────────────────────────────────

def test_motor_rc_link_parse_valid_line():
    link = MotorRcLink.__new__(MotorRcLink)
    link._latest_mode = "MANUAL"
    link._latest_rc_ch1 = 1500
    link._latest_rc_ch2 = 1500
    link._latest_seq = 0
    link._lock = __import__("threading").Lock()
    link._last_valid_time = 0.0
    link._was_fresh = True
    link._staleness_timeout_s = 1.0

    obj = {"seq": 55, "mode": "AUTO", "rc": {"ch1": 1600, "ch2": 1400}}
    link._parse_line(json.dumps(obj))

    assert link.get_mode() == "AUTO"
    assert link.get_rc_channels() == (1600, 1400)
    assert link.get_seq() == 55
    assert not link.is_stale()


def test_motor_rc_link_ignores_gps_fields():
    link = MotorRcLink.__new__(MotorRcLink)
    link._latest_mode = "MANUAL"
    link._latest_rc_ch1 = 1500
    link._latest_rc_ch2 = 1500
    link._latest_seq = 0
    link._lock = __import__("threading").Lock()
    link._last_valid_time = 0.0
    link._was_fresh = True
    link._staleness_timeout_s = 1.0

    obj = {"seq": 1, "mode": "MANUAL", "rc": {"ch1": 1500, "ch2": 1500}, "gps": {"lat": 99.0}, "hdg": 0.0}
    link._parse_line(json.dumps(obj))

    assert link.get_mode() == "MANUAL"
    assert link.get_seq() == 1


# ─── DualArduinoLink merge ─────────────────────────────────────────

def _make_dual_link(sensor_state=None, motor_mode="AUTO", motor_seq=0, motor_stale=False, sensor_stale=False):
    """Helper: build a DualArduinoLink with controlled sub-link states."""
    sensor = SensorGpsLink.__new__(SensorGpsLink)
    sensor._sensor_keys = ["ph", "tds", "turb", "wtemp", "atemp", "hum"]
    sensor._lock = __import__("threading").Lock()
    sensor._was_fresh = not sensor_stale
    sensor._staleness_timeout_s = 3.0

    if sensor_state is None:
        sensor._latest = ArduinoState(
            seq=10, gps_lat=12.916, gps_lon=77.486, gps_fix=1,
            heading=180.0, sensors={"ph": 7.0}, timestamp=time.time(),
        )
    else:
        sensor._latest = sensor_state

    # Control staleness
    if sensor_stale:
        sensor._last_valid_time = 0.0
    else:
        sensor._last_valid_time = time.time()

    motor = MotorRcLink.__new__(MotorRcLink)
    motor._lock = __import__("threading").Lock()
    motor._latest_mode = motor_mode
    motor._latest_rc_ch1 = 1500
    motor._latest_rc_ch2 = 1500
    motor._latest_seq = motor_seq
    motor._was_fresh = not motor_stale
    motor._staleness_timeout_s = 1.0

    if motor_stale:
        motor._last_valid_time = 0.0
    else:
        motor._last_valid_time = time.time()

    return DualArduinoLink(sensor_gps=sensor, motor_rc=motor)


def test_dual_link_merges_gps_from_sensor_and_mode_from_motor():
    link = _make_dual_link(motor_mode="AUTO")
    state = link.get_latest_state()

    assert state.gps_lat == 12.916
    assert state.heading == 180.0
    assert state.mode == "AUTO"
    assert state.sensors["ph"] == 7.0


def test_dual_link_sensor_stale_forces_gps_fix_zero():
    link = _make_dual_link(sensor_stale=True)
    state = link.get_latest_state()

    # gps_fix should be forced to 0 even though sensor reported fix=1
    assert state.gps_fix == 0
    # But lat/lon retain last known values
    assert state.gps_lat == 12.916


def test_dual_link_motor_stale_forces_manual():
    link = _make_dual_link(motor_mode="AUTO", motor_stale=True)
    state = link.get_latest_state()

    # mode should be forced to MANUAL (fail-safe) even though motor reported AUTO
    assert state.mode == "MANUAL"


def test_dual_link_both_fresh_no_overrides():
    link = _make_dual_link(motor_mode="AUTO", sensor_stale=False, motor_stale=False)
    state = link.get_latest_state()

    assert state.gps_fix == 1
    assert state.mode == "AUTO"


def test_dual_link_send_motor_command_forwards_to_motor_only():
    sensor = SensorGpsLink.__new__(SensorGpsLink)
    sensor._lock = __import__("threading").Lock()
    sensor._latest = ArduinoState()
    sensor._last_valid_time = time.time()
    sensor._was_fresh = True

    motor = MotorRcLink.__new__(MotorRcLink)
    motor._lock = __import__("threading").Lock()
    motor._latest_mode = "AUTO"
    motor._latest_rc_ch1 = 1500
    motor._latest_rc_ch2 = 1500
    motor._latest_seq = 0
    motor._serial = _FakeSerialForWrite()
    motor._last_valid_time = time.time()
    motor._was_fresh = True

    dual = DualArduinoLink(sensor_gps=sensor, motor_rc=motor)
    dual.send_motor_command(25, -25)

    sent = json.loads(motor._serial.last_written)
    assert sent["cmd"] == "motor"
    assert sent["l"] == 25
    assert sent["r"] == -25


def test_dual_link_send_ping_forwards_to_motor_only():
    sensor = SensorGpsLink.__new__(SensorGpsLink)
    sensor._lock = __import__("threading").Lock()
    sensor._latest = ArduinoState()
    sensor._last_valid_time = time.time()
    sensor._was_fresh = True

    motor = MotorRcLink.__new__(MotorRcLink)
    motor._lock = __import__("threading").Lock()
    motor._latest_mode = "AUTO"
    motor._latest_rc_ch1 = 1500
    motor._latest_rc_ch2 = 1500
    motor._latest_seq = 0
    motor._serial = _FakeSerialForWrite()
    motor._last_valid_time = time.time()
    motor._was_fresh = True

    dual = DualArduinoLink(sensor_gps=sensor, motor_rc=motor)
    dual.send_ping()

    sent = json.loads(motor._serial.last_written)
    assert sent["cmd"] == "ping"


def test_dual_link_max_seq():
    link = _make_dual_link(motor_seq=99)
    state = link.get_latest_state()
    # sensor seq=10, motor seq=99 → merged seq should be max(10, 99) = 99
    assert state.seq == 99
