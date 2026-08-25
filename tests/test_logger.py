"""
tests/test_logger.py — Unit tests for logger.py (SQLite schema + helpers).
"""

import json
import os
import tempfile
import time

import pytest

from logger import NavLogger


def _make_logger():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    return NavLogger(db_path=db_path), db_path


# ─── Schema creation ──────────────────────────────────────────────────

def test_creates_all_tables():
    logger, db_path = _make_logger()
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()

        assert "telemetry" in tables
        assert "events" in tables
        assert "missions" in tables
        assert "dwell_samples" in tables
        assert "waypoint_results" in tables
    finally:
        logger.close()
        os.unlink(db_path)


# ─── Telemetry logging ───────────────────────────────────────────────

def test_log_telemetry():
    logger, db_path = _make_logger()
    try:
        logger.log_telemetry(
            lat=12.9, lon=77.4, heading_deg=90.0, speed_mps=0.5,
            state="RUNNING", waypoint_index=0, left_power=18, right_power=22,
        )
        import sqlite3
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM telemetry").fetchall()
        conn.close()
        assert len(rows) == 1
    finally:
        logger.close()
        os.unlink(db_path)


# ─── Event logging ───────────────────────────────────────────────────

def test_log_event():
    logger, db_path = _make_logger()
    try:
        logger.log_event("state_transition", "IDLE -> RUNNING")
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT event_type, detail FROM events").fetchone()
        conn.close()
        assert row[0] == "state_transition"
        assert row[1] == "IDLE -> RUNNING"
    finally:
        logger.close()
        os.unlink(db_path)


# ─── Missions ────────────────────────────────────────────────────────

def test_create_and_get_missions():
    logger, db_path = _make_logger()
    try:
        mid = logger.create_mission(waypoint_count=3)
        assert isinstance(mid, int)

        missions = logger.get_missions()
        assert len(missions) == 1
        assert missions[0]["id"] == mid
        assert missions[0]["waypoint_count"] == 3
        assert missions[0]["status"] == "RUNNING"

        logger.update_mission_status(mid, "COMPLETE")
        missions = logger.get_missions()
        assert missions[0]["status"] == "COMPLETE"
    finally:
        logger.close()
        os.unlink(db_path)


# ─── Dwell samples ───────────────────────────────────────────────────

def test_log_and_get_dwell_samples():
    logger, db_path = _make_logger()
    try:
        mid = logger.create_mission(3)
        logger.log_dwell_sample(mid, 0, {"ph": 7.1, "tds": 400.0})
        logger.log_dwell_sample(mid, 0, {"ph": 7.3, "tds": 410.0})

        samples = logger.get_dwell_samples(mid, waypoint_index=0)
        assert len(samples) == 2
        assert samples[0]["sensors"]["ph"] == 7.1
        assert samples[1]["sensors"]["tds"] == 410.0
    finally:
        logger.close()
        os.unlink(db_path)


# ─── Waypoint results ────────────────────────────────────────────────

def test_log_and_get_waypoint_results():
    logger, db_path = _make_logger()
    try:
        mid = logger.create_mission(2)
        logger.log_waypoint_result(
            mid, 0, lat=12.917, lon=77.487,
            arrived_at=time.time(), sample_count=15,
            avg_sensors={"ph": 7.25, "tds": 405.0},
        )

        results = logger.get_waypoint_results(mid)
        assert len(results) == 1
        assert results[0]["avg_sensors"]["ph"] == 7.25
    finally:
        logger.close()
        os.unlink(db_path)
