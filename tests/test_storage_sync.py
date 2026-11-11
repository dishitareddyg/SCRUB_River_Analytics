"""10 s sensor snapshots and offline-first, rate-limited cloud sync."""

from __future__ import annotations

import os
import threading
import time
import unittest

from helpers import GCS, TempDir, mission_payload, override, stm32_packet

from cloud.supabase_client import SupabaseClientWrapper
from cloud.uploader import MissionSyncWorker, SensorUploader
from hardware.gps import GPSWorker
from hardware.live_state import LiveState, PacketRouter
from hardware.motor_controller import MotorControllerWorker
from measurement.snapshot_worker import SensorSnapshotWorker
from mission.validator import validate_mission_payload
from storage.sqlite_manager import SQLiteManager


class Hardware:
    def __init__(self):
        self.gps, self.motor, self.live = GPSWorker(), MotorControllerWorker(), LiveState()
        self.router = PacketRouter(self.gps, self.motor, self.live)

    def packet(self, **kw):
        self.router.on_stm32_packet(stm32_packet(**kw))


class TestSensorSnapshots(unittest.TestCase):
    def test_snapshot_contents(self):
        with TempDir() as tmp:
            db = SQLiteManager(os.path.join(tmp, "s.db"))
            hw = Hardware()
            w = SensorSnapshotWorker(db, hw.live, hw.gps, lambda: "m-1")
            hw.packet(sensors={"ph": 7.0, "tds": None, "turbidity": 9.9,
                               "temperature_c": 25.0, "humidity_percent": None})
            rec = w.capture_once()
            row = db.get_sensor_record(rec["local_record_id"])
            self.assertEqual((row["latitude"], row["longitude"]), GCS)
            self.assertEqual(row["gps_valid"], 1)
            self.assertEqual(row["heading"], 90.0)
            self.assertEqual(row["ph"], 7.0)
            self.assertIsNone(row["tds"])            # NULL kept, record kept
            self.assertEqual(row["mission_id"], "m-1")
            self.assertEqual(row["device_id"], "BOT001")
            self.assertEqual(row["hardware_timestamp"], "2026-11-05T10:41:00.000Z")
            self.assertEqual(row["sync_status"], "PENDING")

    def test_missing_and_stale_gps_stored_without_location(self):
        with TempDir() as tmp, override(GPS_MAX_AGE_SECONDS=0.05):
            db = SQLiteManager(os.path.join(tmp, "s.db"))
            hw = Hardware()
            w = SensorSnapshotWorker(db, hw.live, hw.gps, lambda: None)
            hw.packet(lat=0.0, lon=0.0)                 # no fix
            row = db.get_sensor_record(w.capture_once()["local_record_id"])
            self.assertIsNone(row["latitude"])
            self.assertEqual(row["gps_valid"], 0)
            hw.packet()                                 # fix ...
            time.sleep(0.1)
            hw.packet(lat=None)                         # ... then sensors only, fix ages out
            row = db.get_sensor_record(w.capture_once()["local_record_id"])
            self.assertIsNone(row["latitude"])          # stale coords never attached
            self.assertEqual(row["gps_valid"], 0)
            self.assertGreater(row["gps_age_seconds"], 0.05)
            self.assertEqual(row["ph"], 7.12)

    def test_no_snapshot_without_fresh_hardware_data(self):
        with TempDir() as tmp:
            db = SQLiteManager(os.path.join(tmp, "s.db"))
            hw = Hardware()
            self.assertIsNone(SensorSnapshotWorker(db, hw.live, hw.gps, lambda: None).capture_once())

    def test_one_snapshot_per_interval_not_per_packet(self):
        with TempDir() as tmp, override(SENSOR_STORE_INTERVAL_S=1.0):
            db = SQLiteManager(os.path.join(tmp, "s.db"))
            hw = Hardware()
            w = SensorSnapshotWorker(db, hw.live, hw.gps, lambda: None)
            stop = threading.Event()

            def feed():  # packets 5x faster than storage
                while not stop.is_set():
                    hw.packet()
                    time.sleep(0.2)

            t = threading.Thread(target=feed)
            t.start()
            w.start()
            time.sleep(2.5)
            w.stop()
            stop.set()
            t.join()
            rows = db.recent_sensor_records()
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({r["local_record_id"] for r in rows}), 2)


class FakeTable:
    def __init__(self, cloud, name):
        self.cloud, self.name, self._op = cloud, name, None

    def upsert(self, payload, on_conflict=None):
        self._op = ("upsert", payload, on_conflict)
        return self

    def select(self, *_a, **_k):
        self._op = ("select",)
        self._filters = {}
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def limit(self, _n):
        return self

    def execute(self):
        c = self.cloud
        c.calls.append((self.name, self._op[0]))
        if c.fail_next:
            c.fail_next -= 1
            raise ConnectionError("supabase unavailable")
        tbl = c.tables.setdefault(self.name, {})
        if self._op[0] == "upsert":
            _, payload, key = self._op
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                tbl[tuple(row[k] for k in key.split(","))] = row
            if c.timeout_after_write:
                c.timeout_after_write -= 1
                raise TimeoutError("read timed out")
            return type("R", (), {"data": rows})()
        rows = [r for r in tbl.values() if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": rows})()


class FakeCloud:
    def __init__(self):
        self.tables, self.calls = {}, []
        self.fail_next = 0
        self.timeout_after_write = 0
        self.online = True

    def table(self, name):
        return FakeTable(self, name)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_supabase(cloud):
    sb = SupabaseClientWrapper(client=cloud)
    sb.is_reachable = lambda: cloud.online
    return sb


def add_records(db, n, mission_id=None):
    for i in range(n):
        db.insert_sensor_record({
            "local_record_id": f"00000000-0000-0000-0000-{i:012d}", "mission_id": mission_id,
            "device_id": "BOT001", "recorded_at": f"2026-11-05T10:{i // 60:02d}:{i % 60:02d}.000Z",
            "latitude": 12.9, "longitude": 77.4, "heading": 10.0, "gps_valid": 1,
            "ph": 7.0, "tds": None, "turbidity": None, "temperature_c": None, "humidity_percent": None,
        })


class TestUploader(unittest.TestCase):
    def setUp(self):
        self._tmp = TempDir()
        self.tmp = self._tmp.__enter__()
        self.db = SQLiteManager(os.path.join(self.tmp, "u.db"))
        self.cloud = FakeCloud()
        self.clock = FakeClock()
        self.up = SensorUploader(self.db, make_supabase(self.cloud), clock=self.clock)

    def tearDown(self):
        self.db.close()
        self._tmp.__exit__()

    def synced(self):
        return len(self.cloud.tables.get("sensor_readings", {}))

    def test_offline_keeps_records(self):
        add_records(self.db, 3)
        self.cloud.online = False
        self.assertEqual(self.up.run_once(), "offline")
        self.assertEqual(self.db.sensor_sync_counts()["PENDING"], 3)
        self.clock.t += 10
        self.cloud.online = True                   # Wi-Fi restored
        self.assertEqual(self.up.run_once(), "synced")
        self.assertEqual(self.db.sensor_sync_counts()["SYNCED"], 1)

    def test_backlog_one_record_per_10s_in_order(self):
        add_records(self.db, 25)
        results = [self.up.run_once() for _ in range(10)]   # same instant
        self.assertEqual(results.count("synced"), 1)
        self.assertEqual(results.count("rate_limited"), 9)
        self.clock.t += 9.9
        self.assertEqual(self.up.run_once(), "rate_limited")
        self.clock.t += 0.1
        self.assertEqual(self.up.run_once(), "synced")
        for _ in range(23):
            self.clock.t += 10
            self.up.run_once()
        self.assertEqual(self.synced(), 25)
        uploaded = [k[0] for k in self.cloud.tables["sensor_readings"]]
        self.assertEqual(uploaded, sorted(uploaded))   # recorded_at order
        self.assertEqual(self.up.attempts, 25)

    def test_failure_retry_and_no_deletion(self):
        add_records(self.db, 1)
        self.cloud.fail_next = 1
        self.assertEqual(self.up.run_once(), "failed")
        row = self.db.get_sensor_record("00000000-0000-0000-0000-000000000000")
        self.assertEqual(row["sync_status"], "FAILED")
        self.assertEqual(row["retry_count"], 1)
        self.clock.t += 10
        self.assertEqual(self.up.run_once(), "idle")   # back-off not elapsed (wall clock)
        self.db._conn.execute("UPDATE sensor_records SET next_attempt_at = 0")
        self.assertEqual(self.up.run_once(), "synced")
        self.assertEqual(self.db.get_sensor_record(row["local_record_id"])["sync_status"], "SYNCED")

    def test_timeout_after_insert_is_idempotent(self):
        add_records(self.db, 1)
        self.cloud.timeout_after_write = 1
        self.assertEqual(self.up.run_once(), "failed")
        self.db._conn.execute("UPDATE sensor_records SET next_attempt_at = 0")
        self.clock.t += 10
        self.assertEqual(self.up.run_once(), "synced")
        self.assertEqual(self.synced(), 1)             # same local_record_id, one cloud row

    def test_restart_during_sync_resumes(self):
        add_records(self.db, 3)
        self.up.run_once()
        self.db.close()
        self.db = SQLiteManager(os.path.join(self.tmp, "u.db"))
        up2 = SensorUploader(self.db, make_supabase(self.cloud), clock=self.clock)
        self.assertEqual(self.db.sensor_sync_counts(), {"PENDING": 2, "SYNCED": 1, "FAILED": 0})
        self.assertEqual(up2.run_once(), "synced")
        self.assertEqual(self.synced(), 2)

    def test_mission_records_wait_for_mission_sync(self):
        vm = validate_mission_payload(mission_payload())
        self.db.create_mission_with_waypoints(mission_id=vm.mission_id, device_id=vm.device_id, lake_id=None,
                                              payload_hash=vm.payload_hash, gcs=vm.gcs, polygon=vm.polygon,
                                              waypoints=vm.waypoints)
        self.db.update_mission(vm.mission_id, status="READY", waypoint_load_ack=1)
        add_records(self.db, 1, mission_id=vm.mission_id)
        self.assertEqual(self.up.run_once(), "idle")
        sync = MissionSyncWorker(self.db, make_supabase(self.cloud))
        self.assertEqual(sync.run_once(), 1)
        self.assertEqual(len(self.cloud.tables["mission_waypoints"]), len(vm.waypoints))
        mission_row = self.cloud.tables["missions"][(vm.mission_id,)]
        self.assertEqual(mission_row["status"], "READY")
        self.assertTrue(mission_row["polygon_geom"].startswith("SRID=4326;POLYGON(("))
        self.assertEqual(self.up.run_once(), "synced")
        reading = next(iter(self.cloud.tables["sensor_readings"].values()))
        self.assertEqual(reading["position_geom"], "SRID=4326;POINT(77.40000000 12.90000000)")
        self.assertEqual(sync.run_once(), 0)           # nothing changed
        self.db.update_mission(vm.mission_id, status="ACTIVE")
        self.db.set_waypoint_active(vm.mission_id, 0)
        self.assertEqual(sync.run_once(), 1)           # progress/status re-synced
        cloud_wps = self.cloud.tables["mission_waypoints"]
        self.assertEqual(cloud_wps[(vm.mission_id, 0)]["status"], "ACTIVE")
        self.db.record_waypoint_reached(vm.mission_id, 0, 1, 10.0)
        self.assertEqual(sync.run_once(), 1)
        self.assertEqual(cloud_wps[(vm.mission_id, 0)]["status"], "COMPLETED")
        self.assertEqual(cloud_wps[(vm.mission_id, 1)]["status"], "ACTIVE")
        self.assertEqual(self.cloud.tables["missions"][(vm.mission_id,)]["current_waypoint_index"], 1)
        self.assertEqual(self.db.dirty_waypoints(vm.mission_id), [])
        self.assertEqual(set(cloud_wps[(vm.mission_id, 1)]),
                         {"mission_id", "sequence_order", "latitude", "longitude", "status", "waypoint_geom"})
        self.assertEqual(set(reading) - {"position_geom"},
                         {"local_record_id", "mission_id", "device_id", "recorded_at", "latitude", "longitude",
                          "heading", "ph", "tds", "turbidity", "temperature_c", "humidity_percent"})


if __name__ == "__main__":
    unittest.main()
