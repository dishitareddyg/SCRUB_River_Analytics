"""
tests/test_navigation.py — Unit tests for navigation.py math and state machine.

No hardware; mock ArduinoLink used throughout for controllable state.
"""

import math
from unittest.mock import MagicMock

import pytest

from navigation import (
    NavState,
    NavigationController,
    Waypoint,
    bearing,
    compute_wheel_powers,
    haversine_distance,
    normalize_heading_error,
)
from arduino_link import ArduinoState
from logger import NavLogger


# ─── Helpers ──────────────────────────────────────────────────────────

def _make_nav(
    waypoints=None,
    gps_lat=12.91686,
    gps_lon=77.48698,
    heading=0.0,
    fix=1,
    mode="AUTO",
    arrival_radius_m: float = 2.0,
):
    """Build a NavigationController with a mocked Arduino for controllable state."""
    state = ArduinoState(
        gps_lat=gps_lat, gps_lon=gps_lon, gps_alt=840.0, gps_spd=0.4,
        gps_course=heading, gps_sats=8, gps_fix=fix,
        heading=heading,
        sensors={"ph": 7.2, "tds": 350.0, "turb": 15.0, "wtemp": 26.0, "atemp": 31.0, "hum": 65.0},
        mode=mode,
        rc_ch1=1500, rc_ch2=1500,
    )

    arduino = MagicMock()
    arduino.get_latest_state.return_value = state

    logger = MagicMock(spec=NavLogger)

    nav = NavigationController(
        arduino=arduino,
        logger=logger,
        arrival_radius_m=arrival_radius_m,
        geofence_radius_m=150.0,
        gps_loss_timeout_s=5.0,
        max_mission_runtime_s=1800.0,
        max_motor_power=30,
        default_cruise_power=18,
        steering_k=0.6,
    )
    nav._latest_state = state

    if waypoints:
        nav.load_mission(waypoints)

    return nav, arduino, logger


def _set_state(arduino, **kwargs):
    """Update the state returned by the mocked Arduino."""
    state = arduino.get_latest_state.return_value
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


# ─── Haversine ────────────────────────────────────────────────────────

def test_haversine_known_distance():
    lat1, lon1 = 12.91686, 77.48698
    lat2, lon2 = 12.91786, 77.48698  # 0.001° north ≈ 111.2 m
    dist = haversine_distance(lat1, lon1, lat2, lon2)
    assert abs(dist - 111.2) < 1.0


# ─── Bearing ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("lat1,lon1,lat2,lon2,expected_deg,tol", [
    (0.0, 0.0, 1.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 1.0, 90.0, 1.0),
    (1.0, 0.0, 0.0, 0.0, 180.0, 1.0),
    (0.0, 1.0, 0.0, 0.0, 270.0, 1.0),
])
def test_bearing_known_values(lat1, lon1, lat2, lon2, expected_deg, tol):
    result = bearing(lat1, lon1, lat2, lon2)
    assert abs(result - expected_deg) < tol


# ─── Normalize heading error ──────────────────────────────────────────

@pytest.mark.parametrize("target,current,expected", [
    (350, 10, -20),
    (10, 350, 20),
    (90, 45, 45),
    (45, 90, -45),
    (0, 0, 0),
    (180, 0, 180),
])
def test_normalize_heading_error_wraparound(target, current, expected):
    result = normalize_heading_error(target, current)
    assert abs(result - expected) < 1e-9


def test_normalize_heading_error_180_boundary():
    result = normalize_heading_error(180, 0)
    assert abs(abs(result) - 180) < 1e-9


# ─── Wheel powers ─────────────────────────────────────────────────────

def test_compute_wheel_powers_straight_ahead():
    left, right = compute_wheel_powers(0, base_power=18, k=0.6, max_power=30)
    assert left == 18
    assert right == 18


def test_compute_wheel_powers_turn_right():
    left, right = compute_wheel_powers(10, base_power=18, k=0.6, max_power=30)
    assert left > right


def test_compute_wheel_powers_turn_left():
    left, right = compute_wheel_powers(-10, base_power=18, k=0.6, max_power=30)
    assert right > left


def test_compute_wheel_powers_clamps():
    left, right = compute_wheel_powers(1000, base_power=18, k=0.6, max_power=30)
    assert -30 <= left <= 30
    assert -30 <= right <= 30


# ─── State machine ───────────────────────────────────────────────────

def test_state_transitions_happy_path():
    base_lat = 12.91686
    base_lon = 77.48698
    wp1 = {"lat": base_lat + 0.000001, "lon": base_lon}
    wp2 = {"lat": base_lat + 0.000002, "lon": base_lon}

    nav, arduino, logger = _make_nav(waypoints=[wp1, wp2])

    assert nav.state == NavState.IDLE

    nav.cmd_start()
    assert nav.state == NavState.RUNNING

    nav.cmd_pause()
    assert nav.state == NavState.PAUSED

    nav.cmd_start()
    assert nav.state == NavState.RUNNING

    # First tick: within arrival radius → DWELL
    nav.nav_tick()
    assert nav.state == NavState.DWELL

    # Simulate dwell completion: set _dwell_start_time far in the past
    nav._dwell_start_time = 0.0  # way in the past
    nav.nav_tick()  # should advance from DWELL
    assert nav.state == NavState.RUNNING

    # Second tick: within arrival radius → DWELL
    nav.nav_tick()
    assert nav.state == NavState.DWELL

    nav._dwell_start_time = 0.0
    nav.nav_tick()  # advance → COMPLETE
    assert nav.state == NavState.COMPLETE


def test_stop_from_running():
    nav, _, _ = _make_nav(waypoints=[{"lat": 99.0, "lon": 99.0}])
    nav.cmd_start()
    nav.cmd_stop()
    assert nav.state == NavState.STOPPED


def test_emergency_stop():
    nav, _, _ = _make_nav(waypoints=[{"lat": 99.0, "lon": 99.0}])
    nav.cmd_start()
    nav.cmd_emergency_stop()
    assert nav.state == NavState.STOPPED


def test_start_rejected_empty_waypoints():
    nav, _, logger = _make_nav()
    nav.cmd_start()
    assert nav.state == NavState.IDLE
    logger.log_event.assert_called()


# ─── Effective mode ──────────────────────────────────────────────────

def test_effective_mode_auto():
    nav, arduino, _ = _make_nav(mode="AUTO")
    assert nav._effective_mode() == "AUTO"


def test_effective_mode_manual_physical_switch():
    nav, arduino, _ = _make_nav(mode="MANUAL")
    assert nav._effective_mode() == "MANUAL"


def test_effective_mode_manual_dashboard_override():
    nav, arduino, _ = _make_nav(mode="AUTO")
    nav.set_dashboard_override(True)
    assert nav._effective_mode() == "MANUAL"


def test_effective_mode_auto_when_override_disabled():
    nav, arduino, _ = _make_nav(mode="AUTO")
    nav.set_dashboard_override(False)
    assert nav._effective_mode() == "AUTO"


# ─── Dwell state ─────────────────────────────────────────────────────

def test_dwell_on_arrival():
    base_lat = 12.91686
    base_lon = 77.48698

    nav, arduino, _ = _make_nav(
        waypoints=[{"lat": base_lat, "lon": base_lon}],
        gps_lat=base_lat, gps_lon=base_lon,
        arrival_radius_m=2.0,
    )
    nav.cmd_start()
    nav.nav_tick()

    assert nav.state == NavState.DWELL


def test_manual_during_dwell_discards_samples():
    base_lat = 12.91686
    base_lon = 77.48698

    nav, arduino, _ = _make_nav(
        waypoints=[{"lat": base_lat, "lon": base_lon}],
        gps_lat=base_lat, gps_lon=base_lon,
        arrival_radius_m=2.0,
    )
    nav.cmd_start()
    nav.nav_tick()
    assert nav.state == NavState.DWELL

    # Simulate partial dwell samples
    nav._dwell_samples = [{"ph": 7.0, "tds": 400.0}]

    # Switch Arduino mode to MANUAL
    _set_state(arduino, mode="MANUAL")
    nav.nav_tick()
    assert nav.state == NavState.MANUAL
    assert len(nav._dwell_samples) == 0  # discarded


def test_resume_auto_from_manual():
    nav, arduino, _ = _make_nav(
        waypoints=[{"lat": 12.92, "lon": 77.49}],
        mode="MANUAL",
        arrival_radius_m=2.0,
    )
    nav.cmd_start()
    nav.nav_tick()
    assert nav.state == NavState.MANUAL

    # Switch back to AUTO — should go to IDLE (require explicit Start)
    _set_state(arduino, mode="AUTO")
    nav.nav_tick()
    assert nav.state == NavState.IDLE
