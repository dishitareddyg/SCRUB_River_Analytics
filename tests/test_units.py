"""
tests/test_units.py

Unit tests for the pure-logic components: sensor validation, Haversine
grid matching, local average computation, and motor status line parsing.

Run with:
    pytest tests/test_units.py -v
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from measurement.sensor_validator import SensorValidator
from measurement.grid_matcher import haversine_distance_m
from storage.average_manager import compute_averages


# ---------------------------------------------------------------- validator
# NOTE: with the new STM32 <-> RPi5 combined packet, the STM32 sends
# sensor fields using the same names as the internal/DB fields directly
# (ph/tds/turbidity/temperature_c/humidity_percent), replacing the old
# turb/atemp/hum wire naming.
def test_valid_packet_all_fields():
    v = SensorValidator()
    result = v.validate({"ph": 7.52, "tds": 340.0, "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98})
    assert result == {"ph": 7.52, "tds": 340.0, "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98}


def test_invalid_single_field_becomes_none_others_preserved():
    v = SensorValidator()
    result = v.validate({"ph": 7.52, "tds": None, "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98})
    assert result["ph"] == 7.52
    assert result["tds"] is None
    assert result["turbidity"] == 12.0


def test_string_na_becomes_none():
    v = SensorValidator()
    result = v.validate({"ph": "N/A", "tds": "NA", "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98})
    assert result["ph"] is None
    assert result["tds"] is None


def test_out_of_range_becomes_none_not_clamped():
    v = SensorValidator()
    result = v.validate({"ph": 25.0, "tds": -50, "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98})
    assert result["ph"] is None
    assert result["tds"] is None


def test_nan_and_inf_become_none():
    v = SensorValidator()
    result = v.validate({"ph": float("nan"), "tds": float("inf"), "turbidity": 12.0, "temperature_c": 29, "humidity_percent": 98})
    assert result["ph"] is None
    assert result["tds"] is None


def test_fundamentally_unusable_packet_rejected():
    v = SensorValidator()
    assert v.validate({"unrelated_field": 1}) is None
    assert v.validate("not a dict") is None


# ---------------------------------------------------------------- grid matcher
def test_haversine_zero_distance():
    assert haversine_distance_m(12.9, 77.5, 12.9, 77.5) == 0.0


def test_haversine_known_short_distance():
    # ~ 0.0001 deg latitude is roughly 11.1 meters
    d = haversine_distance_m(12.9000, 77.5000, 12.9001, 77.5000)
    assert 9 < d < 13


# ---------------------------------------------------------------- averages
def test_average_ignores_none_values():
    readings = [
        {"ph": 7.1, "tds": None, "turbidity": 1, "temperature_c": 20, "humidity_percent": 50},
        {"ph": 7.2, "tds": None, "turbidity": 2, "temperature_c": 21, "humidity_percent": 51},
        {"ph": None, "tds": None, "turbidity": 3, "temperature_c": 22, "humidity_percent": 52},
        {"ph": 7.3, "tds": None, "turbidity": 4, "temperature_c": 23, "humidity_percent": 53},
    ]
    avgs = compute_averages(readings)
    assert math.isclose(avgs["ph"], (7.1 + 7.2 + 7.3) / 3, rel_tol=1e-9)
    assert avgs["tds"] is None  # all NULL -> average NULL, never invented


def test_average_all_null_is_null():
    readings = [{"ph": None, "tds": None, "turbidity": None, "temperature_c": None, "humidity_percent": None}]
    avgs = compute_averages(readings)
    assert all(v is None for v in avgs.values())
