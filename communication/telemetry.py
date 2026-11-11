"""
communication/telemetry.py

Builds the application-level live telemetry frame (frontend contract —
NOT a UART packet) and publishes it over MQTT every TELEMETRY_INTERVAL_S.
The WebSocket endpoint (api/app.py) broadcasts the same frame.

Live telemetry reads in-memory state only; it never waits on SQLite
snapshots or cloud uploads.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


def _age(t: Optional[float]) -> Optional[float]:
    return None if t is None else round(time.time() - t, 2)


def _finite(v: Optional[float]) -> Optional[float]:
    return None if v is None or math.isinf(v) else round(v, 2)


class TelemetryHub:
    def __init__(self, *, gps, motor, live_state, navigator, mission_manager,
                 stm32=None, db=None, uploader=None, mqtt=None) -> None:
        self._gps = gps
        self._motor = motor
        self._live = live_state
        self._nav = navigator
        self._missions = mission_manager
        self._stm32 = stm32
        self._db = db
        self._uploader = uploader
        self._mqtt = mqtt
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pending_cache = (0.0, 0)

    # ------------------------------------------------------------------
    def frame(self) -> dict:
        fix = self._gps.get_fix()
        sensors = self._live.snapshot()
        nav = self._nav.status()
        mission = None
        if self._missions:
            mission_id = self._missions.current_mission_id() or nav.get("mission_id")
            if mission_id:
                try:
                    mission = self._missions.status(mission_id)
                except Exception:  # noqa: BLE001
                    mission = None
        total = nav.get("total_waypoints") or (mission or {}).get("total_waypoints", 0)
        idx = nav.get("current_waypoint_index", (mission or {}).get("current_waypoint_index", 0))
        target = nav.get("target_waypoint")
        desired_l, desired_r = self._motor.desired

        return {
            "type": "telemetry",
            "device_id": settings.DEVICE_ID,
            "timestamp": int(time.time() * 1000),
            "mission_id": (mission or {}).get("mission_id") or nav.get("mission_id"),
            "mission_status": (mission or {}).get("status"),
            "position": {
                "latitude": fix.latitude,
                "longitude": fix.longitude,
                "gps_valid": fix.valid,
                "gps_age_s": _finite(fix.age_seconds),
            },
            "heading": fix.heading,
            "heading_valid": fix.heading_valid,
            "navigation": {
                "nav_state": nav.get("nav_state"),
                "current_waypoint_index": idx,
                "total_waypoints": total,
                "completed_waypoints": (mission or {}).get("completed_waypoints", idx),
                "target_waypoint": target,
                "distance_to_target_m": nav.get("distance_to_target_m"),
                "bearing_to_target_deg": nav.get("bearing_to_target_deg"),
                "heading_error_deg": nav.get("heading_error_deg"),
                "progress_percent": (mission or {}).get("progress_percent", 0.0),
                "returning_to_gcs": bool(target and target.get("type") == "GCS" and idx > 0),
                "hold_reason": nav.get("hold_reason"),
            },
            "motors": {
                "state": self._motor.get_state().value,
                "commanded": {"left": desired_l, "right": desired_r},
                "last_sent": {"left": self._motor.last_sent_left, "right": self._motor.last_sent_right,
                              "age_s": _age(self._motor.last_sent_at)},
                "reported": self._motor.reported(),
            },
            "sensors": {
                **sensors.readings,
                "hardware_timestamp": sensors.hardware_timestamp,
                "age_s": _age(sensors.received_at),
                "latitude": fix.latitude if fix.valid else None,
                "longitude": fix.longitude if fix.valid else None,
            },
            "hardware": {
                "stm32_port_open": bool(self._stm32 and self._stm32.connected),
                "stm32_link_alive": bool(self._stm32 and self._stm32.link_alive),
                "last_packet_age_s": _age(self._stm32.last_packet_time) if self._stm32 else None,
            },
            "cloud": {
                "online": getattr(self._uploader, "online", None),
                "pending_records": self._pending_records(),
            },
        }

    def _pending_records(self) -> Optional[int]:
        if not self._db:
            return None
        ts, value = self._pending_cache
        if time.time() - ts > 10:  # cheap: refresh at most every 10 s
            try:
                c = self._db.sensor_sync_counts()
                value = c["PENDING"] + c["FAILED"]
                self._pending_cache = (time.time(), value)
            except Exception:  # noqa: BLE001
                pass
        return value

    # ------------------------------------------------------------------
    # MQTT publisher thread
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self._mqtt:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="TelemetryMQTT", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop_event.wait(max(0.5, settings.TELEMETRY_INTERVAL_S)):
            try:
                self._mqtt.publish(settings.MQTT_TOPIC_TELEMETRY, self.frame())
            except Exception as exc:  # noqa: BLE001
                logger.debug("telemetry publish failed: %s", exc)
