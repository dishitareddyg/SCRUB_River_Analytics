"""
measurement/sensor_validator.py — verbatim from SCRUB_River_Analytics.

Per-field range validation; out-of-range fields → None (not packet reject).
Packet rejected only if not a dict or has no recognizable sensor keys.
"""

from __future__ import annotations

import math
from typing import Optional

from config.settings import settings

_FIELD_MAP = {
    "ph": "ph",
    "tds": "tds",
    "turbidity": "turbidity",
    "temperature_c": "temperature_c",
    "humidity_percent": "humidity_percent",
}

_RANGES = {
    "ph": (settings.PH_MIN, settings.PH_MAX),
    "tds": (settings.TDS_MIN, settings.TDS_MAX),
    "turbidity": (settings.TURBIDITY_MIN, settings.TURBIDITY_MAX),
    "temperature_c": (settings.TEMPERATURE_MIN, settings.TEMPERATURE_MAX),
    "humidity_percent": (settings.HUMIDITY_MIN, settings.HUMIDITY_MAX),
}


def _to_float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or stripped.upper() in ("NA", "N/A", "NULL", "NAN"):
            return None
        try:
            value = float(stripped)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


class SensorValidator:
    def validate(self, sensors: dict) -> Optional[dict]:
        if not isinstance(sensors, dict):
            return None
        recognized_any = any(key in sensors for key in _FIELD_MAP)
        if not recognized_any:
            return None
        result: dict[str, Optional[float]] = {}
        for stm32_key, db_field in _FIELD_MAP.items():
            raw = sensors.get(stm32_key)
            value = _to_float_or_none(raw)
            if value is not None:
                lo, hi = _RANGES[db_field]
                if value < lo or value > hi:
                    value = None
            result[db_field] = value
        return result
