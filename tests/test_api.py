"""HTTP API + WebSocket contract (requires fastapi + httpx)."""

from __future__ import annotations

import os
import unittest

from helpers import GCS, TempDir, mission_payload, override

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "fastapi/httpx not installed")
class TestApi(unittest.TestCase):
    def setUp(self):
        self._tmp = TempDir()
        tmp = self._tmp.__enter__()
        self._ov = override(SQLITE_PATH=os.path.join(tmp, "api.db"),
                            WAYPOINT_JSON_PATH=os.path.join(tmp, "waypoints.json"),
                            MQTT_ENABLED=False, SUPABASE_URL="", SUPABASE_KEY="",
                            API_AUTH_TOKEN="secret", CORS_ALLOWED_ORIGINS=("https://dash.example",))
        self._ov.__enter__()
        from api.app import create_app
        from main import Application
        self.app = Application()          # workers not started; deterministic
        self.app.stm32.last_packet_time = __import__("time").time()
        self.client = TestClient(create_app(self.app))
        self.h = {"Authorization": "Bearer secret"}

    def tearDown(self):
        self.app.db.close()
        self._ov.__exit__(None, None, None)
        self._tmp.__exit__()

    def test_auth_required(self):
        self.assertEqual(self.client.post("/api/missions", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_mission_flow(self):
        payload = mission_payload()
        mid = payload["mission_id"]
        r = self.client.post("/api/missions", json=payload, headers=self.h)
        self.assertEqual(r.status_code, 201, r.text)
        ack = r.json()
        self.assertTrue(ack["waypoint_load_ack"])
        self.assertEqual(ack["status"], "READY")

        bad = dict(payload, mission_id="x")
        r = self.client.post("/api/missions", json=bad, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertIn("errors", r.json())

        r = self.client.post(f"/api/missions/{mid}/start", headers=self.h)
        self.assertEqual(r.status_code, 412)        # no GPS fix yet
        self.app.gps.update(*GCS, 0.0)
        r = self.client.post(f"/api/missions/{mid}/start", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "ACTIVE")
        self.assertEqual(self.client.post(f"/api/missions/{mid}/pause", headers=self.h).json()["status"], "PAUSED")
        self.assertEqual(self.client.post(f"/api/missions/{mid}/resume", headers=self.h).json()["status"], "ACTIVE")
        cur = self.client.get("/api/missions/current", headers=self.h).json()["mission"]
        self.assertEqual(cur["mission_id"], mid)
        r = self.client.post(f"/api/missions/{mid}/abort", headers=self.h).json()
        self.assertEqual((r["status"], r["motors"]), ("ABORTED", "STOPPED"))
        self.assertEqual(self.client.get(f"/api/missions/{mid}", headers=self.h).json()["status"], "ABORTED")
        self.assertEqual(self.client.get("/api/missions/nope", headers=self.h).status_code, 404)
        self.assertEqual(self.client.post("/api/emergency-stop", headers=self.h).status_code, 200)

    def test_websocket_telemetry(self):
        with override(TELEMETRY_INTERVAL_S=0.5):
            with self.client.websocket_connect("/ws/telemetry?token=secret",
                                               headers={"origin": "https://dash.example"}) as ws:
                frame = ws.receive_json()
        self.assertEqual(frame["type"], "telemetry")
        for key in ("device_id", "mission_id", "position", "heading", "navigation", "motors",
                    "sensors", "hardware", "cloud", "timestamp"):
            self.assertIn(key, frame)

    def test_websocket_rejects_bad_token_and_origin(self):
        from starlette.websockets import WebSocketDisconnect
        for url, origin in (("/ws/telemetry?token=bad", "https://dash.example"),
                            ("/ws/telemetry?token=secret", "https://evil.example")):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(url, headers={"origin": origin}) as ws:
                    ws.receive_json()


if __name__ == "__main__":
    unittest.main()
