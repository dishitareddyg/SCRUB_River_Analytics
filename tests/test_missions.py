"""Mission validation, local storage, lifecycle, navigation and reboot recovery."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
import uuid

from helpers import GCS, FakeSerial, TempDir, mission_payload, offset, override

from hardware.gps import GPSWorker
from hardware.motor_controller import MotorControllerWorker
from mission.manager import MissionConflict, MissionManager, MissionPreconditionFailed
from mission.store import WaypointFileStore
from mission.validator import MissionValidationError, validate_mission_payload
from navigation.navigator import Navigator, NavState
from navigation.steering import compute_wheel_powers, haversine_distance, initial_bearing, normalize_heading_error
from storage.sqlite_manager import SQLiteManager


class TestValidator(unittest.TestCase):
    def test_valid(self):
        vm = validate_mission_payload(mission_payload())
        self.assertEqual(vm.waypoints[0]["type"], "GCS")
        self.assertEqual(vm.waypoints[-1]["type"], "GCS")
        self.assertEqual(len(vm.polygon), 4)

    def _errors(self, mutate) -> str:
        p = mission_payload()
        mutate(p)
        with self.assertRaises(MissionValidationError) as cm:
            validate_mission_payload(p)
        return " | ".join(cm.exception.errors)

    def test_rejections(self):
        self.assertIn("mission_id", self._errors(lambda p: p.update(mission_id="nope")))
        self.assertIn("device_id", self._errors(lambda p: p.update(device_id="BOT999")))
        self.assertIn("out of range", self._errors(lambda p: p["polygon"][0].update(latitude=91)))
        self.assertIn("ground_control", self._errors(lambda p: p.pop("ground_control")))
        self.assertIn("duplicate", self._errors(lambda p: p["waypoints"][2].update(sequence_order=1)))
        self.assertIn("ascending", self._errors(lambda p: p["waypoints"].reverse()))
        self.assertIn("final waypoint", self._errors(lambda p: p["waypoints"][-1].update(latitude=GCS[0] + 0.001)))
        self.assertIn("final waypoint", self._errors(lambda p: p["waypoints"][-1].update(type="COVERAGE")))
        self.assertIn("outside polygon", self._errors(
            lambda p: p["waypoints"][2].update(latitude=GCS[0] + 0.01)))
        self.assertIn("type", self._errors(lambda p: p["waypoints"][1].update(type="GRID")))
        self.assertIn("finite number", self._errors(lambda p: p["waypoints"][1].update(longitude="x")))

    def test_self_intersecting_polygon(self):
        def bowtie(p):
            p["polygon"][1], p["polygon"][2] = p["polygon"][2], p["polygon"][1]
        self.assertIn("self-intersect", self._errors(bowtie))

    def test_concave_polygon_accepted(self):
        p = mission_payload()
        # notch the polygon (concave) without excluding route points
        a, b = p["polygon"][2], p["polygon"][3]
        notch = {"latitude": (a["latitude"] + b["latitude"]) / 2 + 0.00001,
                 "longitude": (a["longitude"] + b["longitude"]) / 2}
        p["polygon"].insert(3, notch)
        validate_mission_payload(p)


class Rig:
    """Real GPS + motor controller (fake UART) + navigator + manager on temp SQLite."""

    def __init__(self, tmp, link=True):
        self.db = SQLiteManager(os.path.join(tmp, "t.db"))
        self.store = WaypointFileStore(os.path.join(tmp, "waypoints.json"))
        self.gps = GPSWorker()
        self.motor = MotorControllerWorker()
        self.serial = FakeSerial()
        self.motor.inject_serial(self.serial, threading.Lock())
        self.link = [link]
        self.nav = Navigator(self.gps, self.motor, link_ok=lambda: self.link[0])
        self.mm = MissionManager(self.db, self.nav, self.motor, self.gps, store=self.store,
                                 link_ok=lambda: self.link[0])

    def at(self, lat, lon, heading=0.0):
        self.gps.update(lat, lon, heading)


class TestMissionLifecycle(unittest.TestCase):
    def test_load_store_ack(self):
        with TempDir() as tmp:
            r = Rig(tmp)
            payload = mission_payload()
            ack = r.mm.load_mission(payload)
            self.assertTrue(ack["waypoint_load_ack"])
            self.assertEqual(ack["status"], "READY")
            self.assertEqual(ack["stored_waypoints"], len(payload["waypoints"]))
            self.assertEqual(r.db.count_waypoints(payload["mission_id"]), len(payload["waypoints"]))
            with open(r.store.path) as fh:
                self.assertEqual(json.load(fh)["mission_id"], payload["mission_id"])
            self.assertEqual([f for f in os.listdir(tmp) if f.endswith(".tmp")], [])  # atomic
            # idempotent re-submit, conflicting re-submit
            self.assertTrue(r.mm.load_mission(payload)["duplicate"])
            payload["waypoints"][1]["latitude"] += 0.00001
            with self.assertRaises(MissionConflict):
                r.mm.load_mission(payload)

    def test_start_requires_ready_and_hardware(self):
        with TempDir() as tmp:
            r = Rig(tmp, link=False)
            mid = r.mm.load_mission(mission_payload())["mission_id"]
            with self.assertRaises(MissionPreconditionFailed):
                r.mm.start(mid)
            r.link[0] = True
            with self.assertRaises(MissionPreconditionFailed):
                r.mm.start(mid)  # no GPS fix yet
            r.at(*GCS)
            self.assertEqual(r.mm.start(mid)["status"], "ACTIVE")
            with self.assertRaises(MissionConflict):
                r.mm.start(mid)
            with self.assertRaises(MissionConflict):  # another mission can't load while active
                r.mm.load_mission(mission_payload())

    def test_full_navigation_gcs_polygon_gcs(self):
        with TempDir() as tmp, override(GEOFENCE_RADIUS_M=0):
            r = Rig(tmp)
            payload = mission_payload()
            mid = r.mm.load_mission(payload)["mission_id"]
            r.at(*GCS)
            r.mm.start(mid)
            wps = payload["waypoints"]
            visited = []
            for target in wps[1:]:
                # steer check: commanded powers turn toward the target
                fix = r.gps.get_fix()
                r.nav.tick()
                if r.nav.state == NavState.NAVIGATING:
                    left, right = r.motor.desired
                    err = normalize_heading_error(
                        initial_bearing(fix.latitude, fix.longitude, target["latitude"], target["longitude"]),
                        fix.heading)
                    if abs(err) > 1:
                        self.assertEqual(left > right, err > 0)
                r.at(target["latitude"], target["longitude"], heading=45.0)
                r.nav.tick()
                visited.append(r.db.get_mission(mid)["current_waypoint_index"])
            m = r.db.get_mission(mid)
            self.assertEqual(m["status"], "COMPLETED")
            self.assertEqual(m["progress_percent"], 100.0)
            self.assertEqual(r.motor.desired, (0, 0))
            self.assertTrue(all(w["status"] == "COMPLETED" for w in r.db.get_waypoints(mid)))
            self.assertEqual(visited, sorted(visited))

    def test_pause_resume_abort(self):
        with TempDir() as tmp:
            r = Rig(tmp)
            mid = r.mm.load_mission(mission_payload())["mission_id"]
            r.at(*GCS, heading=0)
            r.mm.start(mid)
            r.nav.tick()
            self.assertNotEqual(r.motor.desired, (0, 0))
            r.mm.pause(mid)
            self.assertEqual(r.motor.desired, (0, 0))
            self.assertEqual(r.serial.packets()[-1], {"left": "+0", "right": "+0", "mode": "auto"})
            r.nav.tick()
            self.assertEqual(r.motor.desired, (0, 0))
            idx = r.db.get_mission(mid)["current_waypoint_index"]
            r.mm.resume(mid)
            self.assertEqual(r.nav.current_index, idx)
            r.nav.tick()
            self.assertNotEqual(r.motor.desired, (0, 0))
            before = len(r.serial.writes)
            res = r.mm.abort(mid)
            self.assertEqual(res["status"], "ABORTED")
            self.assertGreater(len(r.serial.writes), before)  # immediate zero packet
            self.assertEqual(r.serial.packets()[-1], {"left": "+0", "right": "+0", "mode": "auto"})
            self.assertEqual(r.nav.state, NavState.IDLE)

    def test_gps_loss_holds_then_pauses(self):
        with TempDir() as tmp, override(GPS_LOSS_TIMEOUT_S=0.05, GPS_MAX_AGE_SECONDS=0.05):
            r = Rig(tmp)
            mid = r.mm.load_mission(mission_payload())["mission_id"]
            r.at(*GCS)
            r.mm.start(mid)
            time.sleep(0.1)  # fix becomes stale
            r.nav.tick()
            self.assertEqual(r.nav.state, NavState.HOLDING)
            self.assertEqual(r.motor.desired, (0, 0))
            time.sleep(0.1)
            r.nav.tick()
            m = r.db.get_mission(mid)
            self.assertEqual(m["status"], "PAUSED")
            self.assertIn("GPS_LOST", m["notes"])

    def test_link_loss_holds(self):
        with TempDir() as tmp:
            r = Rig(tmp)
            mid = r.mm.load_mission(mission_payload())["mission_id"]
            r.at(*GCS)
            r.mm.start(mid)
            r.link[0] = False
            r.nav.tick()
            self.assertEqual(r.nav.status()["hold_reason"], "STM32_LINK_LOST")
            self.assertEqual(r.motor.desired, (0, 0))

    def test_reboot_recovery_never_moves(self):
        with TempDir() as tmp:
            r = Rig(tmp)
            payload = mission_payload()
            mid = r.mm.load_mission(payload)["mission_id"]
            r.at(*GCS)
            r.mm.start(mid)
            r.nav.tick()
            r.db.close()
            # --- simulated power loss / restart ---
            r2 = Rig(tmp)
            notes = r2.mm.recover_after_restart()
            self.assertTrue(any("PAUSED" in n for n in notes))
            m = r2.db.get_mission(mid)
            self.assertEqual(m["status"], "PAUSED")
            self.assertEqual(r2.db.count_waypoints(mid), len(payload["waypoints"]))
            r2.nav.tick()
            self.assertEqual(r2.motor.desired, (0, 0))
            self.assertEqual(r2.nav.state, NavState.IDLE)
            r2.at(*GCS)
            self.assertEqual(r2.mm.resume(mid)["status"], "ACTIVE")  # explicit operator resume

    def test_interrupted_load_marked_failed(self):
        with TempDir() as tmp:
            r = Rig(tmp)
            vm = validate_mission_payload(mission_payload())
            r.db.create_mission_with_waypoints(mission_id=vm.mission_id, device_id=vm.device_id, lake_id=None,
                                               payload_hash=vm.payload_hash, gcs=vm.gcs, polygon=vm.polygon,
                                               waypoints=vm.waypoints)
            r.mm.recover_after_restart()
            self.assertEqual(r.db.get_mission(vm.mission_id)["status"], "FAILED")


class TestSteeringMath(unittest.TestCase):
    def test_math(self):
        self.assertAlmostEqual(haversine_distance(0, 0, 0, 1), 111195, delta=5)
        self.assertAlmostEqual(initial_bearing(0, 0, 1, 0), 0.0)
        self.assertAlmostEqual(initial_bearing(0, 0, 0, 1), 90.0)
        self.assertEqual(normalize_heading_error(10, 350), 20)
        self.assertEqual(normalize_heading_error(350, 10), -20)
        self.assertEqual(compute_wheel_powers(0, 150, 1.5, 300), (150, 150))
        self.assertEqual(compute_wheel_powers(180, 150, 1.5, 300), (300, -120))


if __name__ == "__main__":
    unittest.main()
