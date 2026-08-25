"""
tests/test_integration_simulated_mission.py — End-to-end simulated mission tests.
"""

import time
from unittest.mock import MagicMock

import pytest

from arduino_link import ArduinoState
from navigation import NavigationController, NavState
from logger import NavLogger


# ─── Helper ──────────────────────────────────────────────────────────

def _make_nav(waypoints, gps_lat=12.91686, gps_lon=77.48698, mode="AUTO"):
    state = ArduinoState(
        gps_lat=gps_lat, gps_lon=gps_lon, gps_fix=1, gps_sats=8,
        heading=0.0, mode=mode,
        sensors={"ph": 7.2, "tds": 350.0, "turb": 15.0, "wtemp": 26.0, "atemp": 31.0, "hum": 65.0},
    )

    arduino = MagicMock()
    arduino.get_latest_state.return_value = state

    logger = MagicMock(spec=NavLogger)
    nav = NavigationController(
        arduino=arduino, logger=logger,
        arrival_radius_m=2.0, geofence_radius_m=150.0,
        gps_loss_timeout_s=5.0, max_mission_runtime_s=1800.0,
        max_motor_power=30, default_cruise_power=18, steering_k=0.6,
    )
    nav.gcs_lat = gps_lat
    nav.gcs_lon = gps_lon
    nav._latest_state = state
    nav.load_mission(waypoints)
    return nav, arduino


# ─── Test 1: Full mission completes ───────────────────────────────────

def test_full_mission_reaches_complete():
    base_lat = 12.91686
    base_lon = 77.48698
    wp1 = {"lat": base_lat + 0.000001, "lon": base_lon}
    wp2 = {"lat": base_lat + 0.000002, "lon": base_lon}

    nav, arduino = _make_nav([wp1, wp2], base_lat, base_lon)
    nav.cmd_start()
    assert nav.state == NavState.RUNNING

    # Tick: within arrival radius → DWELL
    nav.nav_tick()
    assert nav.state == NavState.DWELL

    # Complete first dwell
    nav._dwell_start_time = 0.0
    nav.nav_tick()
    assert nav.state == NavState.RUNNING
    assert nav.current_waypoint_index == 1

    # Tick: within arrival radius of second waypoint → DWELL
    nav.nav_tick()
    assert nav.state == NavState.DWELL

    # Complete second dwell → COMPLETE
    nav._dwell_start_time = 0.0
    nav.nav_tick()
    assert nav.state == NavState.COMPLETE


# ─── Test 2: GPS loss transitions to GPS_LOST ────────────────────────

def test_gps_loss_stops_mission():
    base_lat = 12.91686
    base_lon = 77.48698

    nav, arduino = _make_nav(
        [{"lat": base_lat + 0.01, "lon": base_lon}],
        base_lat, base_lon,
    )
    nav.cmd_start()

    # Manually set watchdog as expired
    nav._watchdog._set_last_feed(time.monotonic() - 6.0)

    nav.nav_tick()
    assert nav.state == NavState.GPS_LOST


# ─── Test 3: Manual override pauses mission ───────────────────────────

def test_manual_override_pauses():
    base_lat = 12.91686
    base_lon = 77.48698

    nav, arduino = _make_nav(
        [{"lat": base_lat + 0.01, "lon": base_lon}],
        base_lat, base_lon,
    )
    nav.cmd_start()
    assert nav.state == NavState.RUNNING

    # Toggle mode to MANUAL
    arduino.get_latest_state.return_value.mode = "MANUAL"
    nav.nav_tick()
    assert nav.state == NavState.MANUAL

    # Toggle back to AUTO — should go to IDLE (require explicit Start)
    arduino.get_latest_state.return_value.mode = "AUTO"
    nav.nav_tick()
    assert nav.state == NavState.IDLE

    # Explicit Start required to resume
    nav.cmd_start()
    assert nav.state == NavState.RUNNING
