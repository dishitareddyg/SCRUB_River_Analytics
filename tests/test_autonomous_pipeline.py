"""
tests/test_autonomous_pipeline.py

Unit tests verifying:
  1. Steering math and wheel power calculations (-999 to +999 clamping).
  2. Motor command packet formatting ({"left": "+100", "right": "+100", "mode": "auto"}).
  3. Navigator state machine (IDLE -> NAVIGATING -> COLLECTING -> COMPLETE).
"""

import json
import threading
import unittest

from navigation.steering import (
    haversine_distance,
    initial_bearing,
    normalize_heading_error,
    compute_wheel_powers,
)
from hardware.motor_controller import MotorControllerWorker, MotorState
from hardware.gps import GPSWorker
from navigation.navigator import Navigator, NavState


class DummySerial:
    def __init__(self):
        self.written = []
        self.is_open = True

    def write(self, data):
        self.written.append(data)


class TestAutonomousPipeline(unittest.TestCase):
    def test_steering_math(self):
        lat1, lon1 = 12.91686, 77.48698
        lat2, lon2 = 12.91686, 77.48798
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        self.assertTrue(100 < dist < 120)

        brg = initial_bearing(lat1, lon1, lat2, lon2)
        self.assertEqual(round(brg), 90)

        self.assertEqual(normalize_heading_error(10, 350), 20)
        self.assertEqual(normalize_heading_error(350, 10), -20)

        # Calculation with custom cruise and steering k
        l, r = compute_wheel_powers(
            heading_error_deg=30.0,
            cruise_power=150,
            steering_k=1.5,
            max_power=300,
        )
        self.assertEqual(l, 195)
        self.assertEqual(r, 105)

        # Clamping test
        l_max, r_max = compute_wheel_powers(
            heading_error_deg=100.0,
            cruise_power=200,
            steering_k=5.0,
            max_power=300,
        )
        self.assertEqual(l_max, 300)
        self.assertEqual(r_max, -300)

    def test_motor_controller_packet_format(self):
        motor = MotorControllerWorker()
        dummy_ser = DummySerial()
        motor.inject_serial(dummy_ser, threading.Lock())

        ok = motor.send_command(100, 100)
        self.assertTrue(ok)
        self.assertEqual(len(dummy_ser.written), 1)
        raw = dummy_ser.written[0].decode("utf-8").strip()
        parsed = json.loads(raw)

        self.assertEqual(parsed["left"], "+100")
        self.assertEqual(parsed["right"], "+100")
        self.assertEqual(parsed["mode"], "auto")

        # Test negative PWM with explicit sign
        motor.send_command(-250, 150)
        raw_neg = dummy_ser.written[1].decode("utf-8").strip()
        parsed_neg = json.loads(raw_neg)
        self.assertEqual(parsed_neg["left"], "-250")
        self.assertEqual(parsed_neg["right"], "+150")
        self.assertEqual(parsed_neg["mode"], "auto")

    def test_navigator_lifecycle(self):
        gps = GPSWorker()
        motor = MotorControllerWorker()
        dummy_ser = DummySerial()
        motor.inject_serial(dummy_ser, threading.Lock())

        nav = Navigator(gps=gps, motor=motor)
        self.assertEqual(nav.state, NavState.IDLE)

        waypoints = [
            {"grid_id": "g1", "lat": 12.91686, "lon": 77.48698, "grid_code": "GRID-01"},
            {"grid_id": "g2", "lat": 12.91786, "lon": 77.48798, "grid_code": "GRID-02"},
        ]
        nav.load_mission(waypoints, mission_id="m1")
        self.assertEqual(nav.current_waypoint["grid_id"], "g1")

        nav.cmd_start()
        self.assertEqual(nav.state, NavState.NAVIGATING)

        nav.cmd_pause()
        self.assertEqual(nav.state, NavState.PAUSED)
        nav.cmd_resume()
        self.assertEqual(nav.state, NavState.NAVIGATING)

        # Transition to collecting at grid 1
        nav._transition(NavState.COLLECTING, "arrived at g1")
        self.assertEqual(nav.state, NavState.COLLECTING)

        # Advance to grid 2
        nav.on_grid_collection_complete()
        nav._advance_to_next_grid()
        self.assertEqual(nav.state, NavState.NAVIGATING)
        self.assertEqual(nav.current_waypoint["grid_id"], "g2")

        # Advance to completion
        nav.on_grid_collection_complete()
        nav._advance_to_next_grid()
        self.assertEqual(nav.state, NavState.COMPLETE)


    def test_measurement_handoff_and_sqlite(self):
        import tempfile
        import os
        from storage.sqlite_manager import SQLiteManager
        from measurement.grid_matcher import GridMatcher
        from measurement.session_manager import SessionManager
        from measurement.sensor_validator import SensorValidator
        from measurement.measurement_manager import MeasurementManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            db = SQLiteManager(path=db_path)
            # Add grid definition to cache
            grid_obj = {
                "grid_id": "grid-test-01",
                "lake_id": "lake-01",
                "grid_code": "G01",
                "grid_size_m": 10.0,
                "center_lat": 12.91686,
                "center_lon": 77.48698,
            }
            db.replace_grid_cache([grid_obj])

            gps = GPSWorker()
            gps.update(12.91686, 77.48698, heading=90.0)

            motor = MotorControllerWorker()
            motor.update(0, 0) # IDLE
            self.assertEqual(motor.get_state(), MotorState.IDLE)

            nav = Navigator(gps=gps, motor=motor)
            session_mgr = SessionManager(db)
            validator = SensorValidator()

            grid_matcher = GridMatcher(db)

            mm = MeasurementManager(
                sqlite_manager=db,
                gps_worker=gps,
                motor_worker=motor,
                grid_matcher=grid_matcher,
                session_manager=session_mgr,
                sensor_validator=validator,
                navigator=nav,
            )
            nav._on_grid_arrived = mm.on_grid_arrived

            # Signal arrival at grid
            mm.on_grid_arrived(grid_obj)

            # Process packet
            packet = {
                "device_id": "BOT001",
                "motors": {"left": 0, "right": 0},
                "gps": {"latitude": 12.91686, "longitude": 77.48698},
                "compass": {"heading": 90.0},
                "sensors": {
                    "ph": 7.2, "tds": 250.0, "turbidity": 12.0,
                    "temperature_c": 26.5, "humidity_percent": 65.0
                }
            }
            mm.on_stm32_packet(packet)

            # Check that sample was recorded in SQLite
            session = db.get_active_session("grid-test-01")
            self.assertIsNotNone(session)
            self.assertEqual(session["sample_count"], 1)

            readings = db.get_readings_for_session(session["session_id"])
            self.assertEqual(len(readings), 1)
            self.assertEqual(readings[0]["ph"], 7.2)

        finally:
            try:
                db.close()
            except Exception:
                pass
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
