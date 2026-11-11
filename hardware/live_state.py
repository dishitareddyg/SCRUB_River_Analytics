"""
hardware/live_state.py

Latest valid hardware state kept in memory (updated on every 2 s STM32
packet) plus the router that dispatches each parsed packet to GPS,
motor-state and sensor holders.

Consumers:
  * SensorSnapshotWorker — persists one snapshot every SENSOR_STORE_INTERVAL_S
  * TelemetryHub         — live MQTT / WebSocket frames
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from hardware.protocol import SENSOR_KEYS, parse_stm32_packet
from measurement.sensor_validator import SensorValidator
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SensorState:
    device_id: Optional[str] = None
    hardware_timestamp: Optional[str] = None   # packet["timestamp"]
    received_at: Optional[float] = None        # RPi wall clock (epoch s)
    readings: dict = field(default_factory=lambda: {k: None for k in SENSOR_KEYS})


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = SensorState()

    def update(self, device_id, hardware_timestamp, readings: dict, received_at: float) -> None:
        with self._lock:
            self._state = SensorState(
                device_id=device_id or self._state.device_id,
                hardware_timestamp=hardware_timestamp,
                received_at=received_at,
                readings={k: readings.get(k) for k in SENSOR_KEYS},
            )

    def snapshot(self) -> SensorState:
        with self._lock:
            s = self._state
            return SensorState(s.device_id, s.hardware_timestamp, s.received_at, dict(s.readings))

    def age_seconds(self) -> float:
        with self._lock:
            t = self._state.received_at
        return time.time() - t if t is not None else float("inf")


class PacketRouter:
    """STM32Worker.on_packet callback: parse once, fan out to holders."""

    def __init__(self, gps, motor, live_state: LiveState,
                 validator: Optional[SensorValidator] = None, health=None) -> None:
        self._gps = gps
        self._motor = motor
        self._live = live_state
        self._validator = validator or SensorValidator()
        self._health = health
        self._warned: set[str] = set()

    def on_stm32_packet(self, raw: dict) -> None:
        pkt = parse_stm32_packet(raw)
        if pkt is None:
            return
        now = time.time()
        for w in pkt.warnings:
            if w not in self._warned:  # log each warning type once to avoid spam
                self._warned.add(w)
                logger.warning("STM32 packet warning: %s", w)

        self._gps.update(pkt.latitude, pkt.longitude, pkt.heading, now)

        if pkt.motor_left is not None and pkt.motor_right is not None:
            self._motor.update(pkt.motor_left, pkt.motor_right, now)

        readings = self._validator.validate(pkt.sensors) or {k: None for k in SENSOR_KEYS}
        self._live.update(pkt.device_id, pkt.timestamp, readings, now)
