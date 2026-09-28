"""
monitoring/health.py

Lightweight, thread-safe internal health state for the autonomous nav service.
Published periodically over MQTT by main.py so operators can monitor
the bot's subsystem status without any extra HTTP server.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class HealthSnapshot:
    # Navigation
    nav_state: str = "IDLE"
    mission_id: Optional[str] = None
    current_grid_index: int = 0
    total_grids: int = 0

    # Hardware link
    stm32_connected: bool = False
    last_sensor_packet_time: Optional[float] = None

    # GPS
    gps_valid: bool = False
    last_gps_time: Optional[float] = None

    # Motor state (as reported by STM32)
    motor_state: str = "UNKNOWN"

    # Cloud / MQTT
    mqtt_connected: bool = False
    cloud_reachable: Optional[bool] = None
    last_successful_upload_time: Optional[float] = None
    pending_upload_count: int = 0

    sqlite_ok: bool = True
    snapshot_time: float = field(default_factory=time.time)


class HealthMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = HealthSnapshot()

    # ------------------------------------------------------------------
    def set_nav_state(self, state: str) -> None:
        with self._lock:
            self._state.nav_state = state

    def set_mission(self, mission_id: Optional[str], current: int, total: int) -> None:
        with self._lock:
            self._state.mission_id = mission_id
            self._state.current_grid_index = current
            self._state.total_grids = total

    def set_stm32_connected(self, connected: bool) -> None:
        with self._lock:
            self._state.stm32_connected = connected

    def set_last_sensor_packet_time(self, ts: float) -> None:
        with self._lock:
            self._state.last_sensor_packet_time = ts

    def set_gps_valid(self, valid: bool, ts: float) -> None:
        with self._lock:
            self._state.gps_valid = valid
            self._state.last_gps_time = ts

    def set_motor_state(self, state: str) -> None:
        with self._lock:
            self._state.motor_state = state

    def set_mqtt_connected(self, connected: bool) -> None:
        with self._lock:
            self._state.mqtt_connected = connected

    def set_cloud_reachable(self, reachable: bool) -> None:
        with self._lock:
            self._state.cloud_reachable = reachable

    def set_last_successful_upload_time(self, ts: float) -> None:
        with self._lock:
            self._state.last_successful_upload_time = ts

    def set_pending_upload_count(self, count: int) -> None:
        with self._lock:
            self._state.pending_upload_count = count

    def set_sqlite_ok(self, ok: bool) -> None:
        with self._lock:
            self._state.sqlite_ok = ok

    def snapshot(self) -> dict:
        with self._lock:
            self._state.snapshot_time = time.time()
            return asdict(self._state)
