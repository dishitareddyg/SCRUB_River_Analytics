"""
navigation/steering.py

Pure mathematical helpers for navigation — no I/O, no state.
All functions are independent and fully testable in isolation.

Haversine distance, initial bearing, heading error normalisation,
and the proportional steering mixer that converts heading error to
left/right PWM values.
"""

from __future__ import annotations

import math

_EARTH_RADIUS_M = 6_371_000.0


# ---------------------------------------------------------------------------
# Geo math
# ---------------------------------------------------------------------------

def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return great-circle distance in metres between two WGS-84 points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Return the initial bearing (degrees, [0, 360)) from point 1 to point 2.
    0 = North, 90 = East, 180 = South, 270 = West.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    )
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def normalize_heading_error(target_bearing: float, current_heading: float) -> float:
    """
    Signed angular difference target − current, normalised to (-180, 180].
    Positive → turn right, negative → turn left.
    """
    error = (target_bearing - current_heading) % 360
    if error > 180:
        error -= 360
    return error


# ---------------------------------------------------------------------------
# Proportional steering mixer
# ---------------------------------------------------------------------------

def compute_wheel_powers(
    heading_error_deg: float,
    cruise_power: int,
    steering_k: float,
    max_power: int,
) -> tuple[int, int]:
    """
    Proportional differential-drive steering mixer.

    left  = clamp(cruise + k * error,  -max, +max)
    right = clamp(cruise - k * error,  -max, +max)

    PWM range: -max_power to +max_power  (e.g. -999 to +999)
    Returns (left_pwm, right_pwm) as integers.
    """
    left = cruise_power + steering_k * heading_error_deg
    right = cruise_power - steering_k * heading_error_deg
    left_int = int(round(max(-max_power, min(max_power, left))))
    right_int = int(round(max(-max_power, min(max_power, right))))
    return left_int, right_int
