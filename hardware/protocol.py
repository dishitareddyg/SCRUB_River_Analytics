"""
hardware/protocol.py

The STM32 <-> Raspberry Pi 5 UART contract, exactly as documented in
SOFTWARE ARCHITECTURE.docx.  Nothing here may change field names,
nesting or frequency.

STM32 -> RPi (1 packet / 2 s, newline-delimited JSON):
    {"device_id":"BOT001","timestamp":"2026-11-05T10:41:00.000Z",
     "motors":{"left":L,"right":R},
     "gps":{"latitude":lat,"longitude":lon},
     "compass":{"heading":hdg},
     "sensors":{"ph":ph,"tds":tds,"turbidity":turb,
                "temperature_c":temp,"humidity_percent":hum}}

RPi -> STM32 (1 packet / 2 s, newline-delimited JSON):
    {"left":"+100","right":"+100","mode":"auto"}
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import HARDWARE_PWM_LIMIT, settings

SENSOR_KEYS = ("ph", "tds", "turbidity", "temperature_c", "humidity_percent")


def _num(value: Any) -> Optional[float]:
    """Finite JSON number -> float; anything else (null, bool, NaN, text) -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        # Tolerate numeric strings from firmware, never sentinel words.
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


@dataclass
class Stm32Packet:
    """Parsed STM32 packet. Invalid/missing values are None."""

    device_id: Optional[str]
    timestamp: Optional[str]
    motor_left: Optional[float]
    motor_right: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]
    heading: Optional[float]
    sensors: dict = field(default_factory=dict)  # SENSOR_KEYS -> float | None
    warnings: list = field(default_factory=list)

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def _section(packet: dict, key: str, warnings: list) -> dict:
    value = packet.get(key)
    if isinstance(value, dict):
        return value
    warnings.append(f"missing_or_invalid_{key}")
    return {}


def parse_stm32_packet(packet: Any) -> Optional[Stm32Packet]:
    """
    Parse one decoded STM32 JSON object using the exact documented keys:
      device_id, timestamp, motors.left, motors.right, gps.latitude,
      gps.longitude, compass.heading, sensors.ph, sensors.tds,
      sensors.turbidity, sensors.temperature_c, sensors.humidity_percent
    Returns None if the payload is not a JSON object.
    """
    if not isinstance(packet, dict):
        return None
    warnings: list[str] = []

    device_id = packet.get("device_id")
    device_id = device_id if isinstance(device_id, str) and device_id else None
    timestamp = packet.get("timestamp")
    timestamp = timestamp if isinstance(timestamp, str) and timestamp else None

    motors = _section(packet, "motors", warnings)
    gps = _section(packet, "gps", warnings)
    compass = _section(packet, "compass", warnings)
    sensors_raw = _section(packet, "sensors", warnings)

    motor_left = _num(motors.get("left"))
    motor_right = _num(motors.get("right"))

    lat = _num(gps.get("latitude"))
    lon = _num(gps.get("longitude"))
    if lat is not None and not -90.0 <= lat <= 90.0:
        warnings.append("latitude_out_of_range")
        lat = None
    if lon is not None and not -180.0 <= lon <= 180.0:
        warnings.append("longitude_out_of_range")
        lon = None
    if lat is None or lon is None:
        lat = lon = None
    elif settings.GPS_REJECT_NULL_ISLAND and lat == 0.0 and lon == 0.0:
        warnings.append("gps_null_island")
        lat = lon = None

    heading = _num(compass.get("heading"))
    if heading is not None:
        heading = normalize_heading(heading)

    sensors = {key: _num(sensors_raw.get(key)) for key in SENSOR_KEYS}

    return Stm32Packet(
        device_id=device_id,
        timestamp=timestamp,
        motor_left=motor_left,
        motor_right=motor_right,
        latitude=lat,
        longitude=lon,
        heading=heading,
        sensors=sensors,
        warnings=warnings,
    )


def normalize_heading(raw_heading: float) -> float:
    """Apply compass offset + magnetic declination, normalise to [0, 360)."""
    return (raw_heading + settings.COMPASS_OFFSET_DEG + settings.COMPASS_DECLINATION_DEG) % 360.0


def clamp_pwm(value: float, max_power: Optional[int] = None) -> int:
    limit = min(abs(int(max_power if max_power is not None else settings.MAX_MOTOR_POWER)), HARDWARE_PWM_LIMIT)
    return max(-limit, min(limit, int(round(value))))


def format_pwm(value: int) -> str:
    """Explicit sign as documented: +100, -50, +0."""
    return f"+{value}" if value >= 0 else str(value)


def build_motor_command(left: float, right: float, mode: Optional[str] = None,
                        max_power: Optional[int] = None) -> bytes:
    """
    Build the exact documented RPi -> STM32 packet:
        {"left":"+100","right":"+100","mode":"auto"}\\n
    Values are clamped to ±MAX_MOTOR_POWER (never beyond ±999).
    """
    payload = {
        "left": format_pwm(clamp_pwm(left, max_power)),
        "right": format_pwm(clamp_pwm(right, max_power)),
        "mode": mode or settings.MOTOR_COMMAND_MODE,
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
