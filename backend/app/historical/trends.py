"""Trend analysis via simple linear regression - no Machine Learning.

Every function here works with plain ``(x, y)`` float pairs (``x`` is
conventionally "seconds since the window start", ``y`` is the sensor/
analytics value) so it stays fully decoupled from timestamps, the
database, and the HTTP layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from app.historical.statistics import percent_change

#: Below this absolute percent change, a series is classified STABLE.
STABLE_THRESHOLD_PERCENT = 2.0

#: At or above this absolute percent change, a series is classified as
#: a "rapid" increase/decrease rather than a plain one.
RAPID_THRESHOLD_PERCENT = 15.0


class TrendDirection(str, Enum):
    """A qualitative trend classification.

    Attributes:
        INCREASING: A moderate upward trend.
        DECREASING: A moderate downward trend.
        STABLE: No meaningful change.
        RAPID_INCREASE: A sharp upward trend.
        RAPID_DECREASE: A sharp downward trend.
        INSUFFICIENT_DATA: Too few data points to classify a trend.
    """

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    RAPID_INCREASE = "rapid_increase"
    RAPID_DECREASE = "rapid_decrease"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class LinearTrend:
    """The result of fitting a simple ordinary-least-squares line.

    Attributes:
        slope: Change in ``y`` per unit ``x`` (e.g. value per second,
            if ``x`` is seconds).
        intercept: The fitted line's value at ``x = 0``.
        r_squared: Coefficient of determination, ``0.0``-``1.0``,
            reflecting how well the line fits the data (used as the
            basis for :func:`trend_confidence`). ``0.0`` when it
            cannot be computed (fewer than 2 points, or no variance in
            ``x``/``y``).
    """

    slope: float
    intercept: float
    r_squared: float


def linear_trend(points: Sequence[Tuple[float, float]]) -> Optional[LinearTrend]:
    """Fit an ordinary-least-squares line through ``(x, y)`` points.

    Pure statistical method (closed-form OLS) - not Machine Learning.

    Args:
        points: A sequence of ``(x, y)`` pairs. ``x`` is conventionally
            elapsed seconds since the window start; ``y`` is the
            measured value.

    Returns:
        A :class:`LinearTrend`, or ``None`` if fewer than 2 points are
        supplied.
    """
    n = len(points)
    if n < 2:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_yy = sum((y - mean_y) ** 2 for y in ys)

    if ss_xx == 0:
        # Every point shares the same x (e.g. identical timestamps) -
        # no meaningful slope can be fit.
        return LinearTrend(slope=0.0, intercept=mean_y, r_squared=0.0)

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    if ss_yy == 0:
        # Perfectly flat series: a flat line fits it perfectly.
        r_squared = 1.0
    else:
        ss_residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r_squared = max(0.0, 1.0 - ss_residual / ss_yy)

    return LinearTrend(slope=slope, intercept=intercept, r_squared=r_squared)


def rate_of_change(trend: Optional[LinearTrend], seconds_per_unit: float = 3600.0) -> Optional[float]:
    """Convert a fitted slope (value/second) into value-per-``unit``.

    Args:
        trend: A fitted :class:`LinearTrend`, or ``None``.
        seconds_per_unit: Number of seconds in the desired reporting
            unit. Defaults to ``3600`` (i.e. report per hour).

    Returns:
        The slope expressed as value-per-unit-time, or ``None`` if
        ``trend`` is ``None``.
    """
    if trend is None:
        return None
    return trend.slope * seconds_per_unit


def trend_confidence(trend: Optional[LinearTrend]) -> Optional[float]:
    """Return a ``0.0``-``1.0`` confidence score for a fitted trend.

    Confidence is simply the line's coefficient of determination
    (``r_squared``): a straight, consistent trend fits well and scores
    high; a noisy/scattered series fits poorly and scores low.

    Args:
        trend: A fitted :class:`LinearTrend`, or ``None``.

    Returns:
        ``trend.r_squared``, or ``None`` if ``trend`` is ``None``.
    """
    if trend is None:
        return None
    return round(trend.r_squared, 4)


def classify_trend(
    change_percent: Optional[float],
    *,
    stable_threshold: float = STABLE_THRESHOLD_PERCENT,
    rapid_threshold: float = RAPID_THRESHOLD_PERCENT,
) -> TrendDirection:
    """Classify a percent change into a qualitative :class:`TrendDirection`.

    Args:
        change_percent: Percent change over the window (see
            :func:`app.historical.statistics.percent_change`), or
            ``None`` if it could not be computed.
        stable_threshold: Absolute percent change below which the
            series is considered STABLE.
        rapid_threshold: Absolute percent change at/above which the
            series is considered a "rapid" increase/decrease.

    Returns:
        The classified :class:`TrendDirection`.
    """
    if change_percent is None:
        return TrendDirection.INSUFFICIENT_DATA

    magnitude = abs(change_percent)
    if magnitude < stable_threshold:
        return TrendDirection.STABLE
    if change_percent > 0:
        return TrendDirection.RAPID_INCREASE if magnitude >= rapid_threshold else TrendDirection.INCREASING
    return TrendDirection.RAPID_DECREASE if magnitude >= rapid_threshold else TrendDirection.DECREASING


def trend_percentage(first: Optional[float], last: Optional[float]) -> Optional[float]:
    """Return the percent change from ``first`` to ``last``.

    Thin, explicitly-named re-export of
    :func:`app.historical.statistics.percent_change` so callers in
    this module don't need to import two modules for one concept.

    Args:
        first: The starting value.
        last: The ending value.

    Returns:
        The percent change, or ``None`` if undefined (see
        :func:`app.historical.statistics.percent_change`).
    """
    return percent_change(first, last)


__all__: List[str] = [
    "TrendDirection",
    "LinearTrend",
    "linear_trend",
    "rate_of_change",
    "trend_confidence",
    "classify_trend",
    "trend_percentage",
    "STABLE_THRESHOLD_PERCENT",
    "RAPID_THRESHOLD_PERCENT",
]
