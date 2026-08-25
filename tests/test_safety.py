"""
tests/test_safety.py — Unit tests for safety.py

Tests: geofence, GPS watchdog, mission timer.
"""

import time

import pytest

from safety import GpsWatchdog, MissionTimer, check_geofence


# ─── Geofence ─────────────────────────────────────────────────────────

def test_geofence_within_radius():
    gcs_lat, gcs_lon = 12.91686, 77.48698
    current_lat = gcs_lat + 50.0 / 111320.0
    assert check_geofence(current_lat, gcs_lon, gcs_lat, gcs_lon, radius_m=150.0) is True


def test_geofence_breach():
    gcs_lat, gcs_lon = 12.91686, 77.48698
    current_lat = gcs_lat + 200.0 / 111320.0
    assert check_geofence(current_lat, gcs_lon, gcs_lat, gcs_lon, radius_m=150.0) is False


def test_geofence_at_gcs():
    gcs_lat, gcs_lon = 12.91686, 77.48698
    assert check_geofence(gcs_lat, gcs_lon, gcs_lat, gcs_lon, radius_m=150.0) is True


# ─── GpsWatchdog ──────────────────────────────────────────────────────

def test_watchdog_not_expired_after_feed():
    w = GpsWatchdog(timeout_s=5.0)
    w.feed()
    assert w.expired() is False


def test_watchdog_expires():
    w = GpsWatchdog(timeout_s=5.0)
    w._set_last_feed(time.monotonic() - 6.0)
    assert w.expired() is True


def test_watchdog_not_expired_within_timeout():
    w = GpsWatchdog(timeout_s=5.0)
    w._set_last_feed(time.monotonic() - 3.0)
    assert w.expired() is False


def test_watchdog_feed_resets():
    w = GpsWatchdog(timeout_s=5.0)
    w._set_last_feed(time.monotonic() - 10.0)
    assert w.expired() is True
    w.feed()
    assert w.expired() is False


# ─── MissionTimer ─────────────────────────────────────────────────────

def test_timer_not_started():
    t = MissionTimer(max_runtime_s=1800.0)
    assert t.expired() is False


def test_timer_expires():
    t = MissionTimer(max_runtime_s=1800.0)
    t._set_start_time(time.monotonic() - 1801.0)
    assert t.expired() is True


def test_timer_not_expired_within_limit():
    t = MissionTimer(max_runtime_s=1800.0)
    t._set_start_time(time.monotonic() - 900.0)
    assert t.expired() is False


def test_timer_start_resets():
    t = MissionTimer(max_runtime_s=1800.0)
    t._set_start_time(time.monotonic() - 2000.0)
    assert t.expired() is True
    t.start()
    assert t.expired() is False
