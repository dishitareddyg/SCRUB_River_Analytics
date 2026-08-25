"""
tests/test_telemetry_schema.py — Telemetry message shape and command handling tests.
"""

import json
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from navigation import NavState, NavigationController
from arduino_link import ArduinoState
from logger import NavLogger
from server import build_telemetry, _dispatch_command


# ─── Helpers ──────────────────────────────────────────────────────────

REQUIRED_TELEMETRY_FIELDS = {
    "type": str,
    "lat": float,
    "lon": float,
    "heading_deg": float,
    "speed_mps": float,
    "state": str,
    "effective_mode": str,
    "current_waypoint_index": int,
    "total_waypoints": int,
    "satellites": int,
    "fix_quality": int,
    "left_power": int,
    "right_power": int,
    "sensors": dict,
    "target_bearing": float,
    "heading_error": float,
    "distance_to_target": float,
    "timestamp": float,
}


def _make_nav():
    state = ArduinoState(
        gps_lat=12.91686, gps_lon=77.48698, gps_alt=840.0,
        gps_spd=0.5, gps_course=45.0, gps_sats=8, gps_fix=1,
        heading=45.0,
        sensors={"ph": 7.2, "tds": 350.0, "turb": 15.0, "wtemp": 26.0, "atemp": 31.0, "hum": 65.0},
        mode="AUTO",
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
    nav._latest_state = state
    return nav


def _make_state_dict():
    nav = _make_nav()
    nav.nav_tick()
    return nav


# ─── Telemetry schema ─────────────────────────────────────────────────

def test_telemetry_has_all_required_fields():
    nav = _make_nav()
    nav.nav_tick()

    telem = build_telemetry(nav)

    for field, expected_type in REQUIRED_TELEMETRY_FIELDS.items():
        assert field in telem, f"Missing field: '{field}'"
        assert isinstance(telem[field], expected_type), (
            f"Field '{field}': expected {expected_type.__name__}, "
            f"got {type(telem[field]).__name__}"
        )

    assert telem["type"] == "telemetry"


# ─── Command dispatch ─────────────────────────────────────────────────

def _make_server_state():
    nav = _make_nav()
    logger = MagicMock(spec=NavLogger)
    return {
        "nav": nav,
        "logger": logger,
        "firebase": None,
        "broadcast_interval": 0.33,
        "clients": set(),
        "stop_event": asyncio.Event(),
    }


@pytest.mark.asyncio
async def test_unknown_command_returns_error():
    state = _make_server_state()

    sent = []
    fake_ws = AsyncMock()
    fake_ws.send_json = AsyncMock(side_effect=lambda msg: sent.append(msg))

    await _dispatch_command(fake_ws, {"type": "not_real"}, state)

    assert len(sent) == 1
    assert sent[0]["type"] == "error"


@pytest.mark.asyncio
async def test_load_mission_updates_waypoints():
    state = _make_server_state()

    fake_ws = AsyncMock()
    fake_ws.send_json = AsyncMock()

    waypoints = [{"lat": 12.917, "lon": 77.487}]
    await _dispatch_command(fake_ws, {"type": "load_mission", "waypoints": waypoints}, state)

    assert len(state["nav"].waypoints) == 1
    assert abs(state["nav"].waypoints[0].lat - 12.917) < 1e-4


@pytest.mark.asyncio
async def test_set_manual_command():
    state = _make_server_state()

    fake_ws = AsyncMock()
    fake_ws.send_json = AsyncMock()

    await _dispatch_command(fake_ws, {"type": "set_manual", "enabled": True}, state)
    assert state["nav"]._dashboard_override is True

    await _dispatch_command(fake_ws, {"type": "set_manual", "enabled": False}, state)
    assert state["nav"]._dashboard_override is False


@pytest.mark.asyncio
async def test_set_gcs_command():
    state = _make_server_state()

    fake_ws = AsyncMock()
    fake_ws.send_json = AsyncMock()

    await _dispatch_command(fake_ws, {"type": "set_gcs", "lat": 12.5, "lon": 77.5}, state)
    assert state["nav"].gcs_lat == 12.5
    assert state["nav"].gcs_lon == 77.5
