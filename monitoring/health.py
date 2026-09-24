"""
monitoring/health.py

Lightweight, thread-safe internal health state (spec section 47).
No HTTP server / extra dependencies are added -- the snapshot is published
periodically over MQTT by main.py, which is sufficient for monitoring
without introducing unnecessary complexity on the Pi.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class HealthSnapshot:
    # GPS/compass and motors no longer have their own serial link (see
    # the STM32 <-> RPi5 combined-packet architecture) -- their liveness
    # is entirely a function of `stm32_connected` / `last_sensor_packet_time`
    # below, plus the age-based validity applied when each is read.
    gps_valid: bool = False
    last_gps_time: Optional[float] = None
    stm32_connected: bool = False
    last_sensor_packet_time: Optional[float] = None
    motor_state: str = "UNKNOWN"
    mqtt_connected: bool = False
    cloud_reachable: Optional[bool] = None
    last_successful_upload_time: Optional[float] = None
    sqlite_ok: bool = True
    pending_upload_count: int = 0
    snapshot_time: float = field(default_factory=time.time)


class HealthMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = HealthSnapshot()

    def set_gps_valid(self, valid: bool, ts: float) -> None:
        with self._lock:
            self._state.gps_valid = valid
            self._state.last_gps_time = ts

    def set_stm32_connected(self, connected: bool) -> None:
        with self._lock:
            self._state.stm32_connected = connected

    def set_last_sensor_packet_time(self, ts: float) -> None:
        with self._lock:
            self._state.last_sensor_packet_time = ts

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

    def set_sqlite_ok(self, ok: bool) -> None:
        with self._lock:
            self._state.sqlite_ok = ok

    def set_pending_upload_count(self, count: int) -> None:
        with self._lock:
            self._state.pending_upload_count = count

    def snapshot(self) -> dict:
        with self._lock:
            self._state.snapshot_time = time.time()
            return asdict(self._state)
