"""Unit tests for :mod:`app.historical.trends`."""

from __future__ import annotations

import pytest

from app.historical.trends import (
    TrendDirection,
    classify_trend,
    linear_trend,
    rate_of_change,
    trend_confidence,
    trend_percentage,
)


def test_linear_trend_perfect_line() -> None:
    points = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]
    fitted = linear_trend(points)
    assert fitted is not None
    assert fitted.slope == pytest.approx(1.0)
    assert fitted.intercept == pytest.approx(1.0)
    assert fitted.r_squared == pytest.approx(1.0)


def test_linear_trend_flat_line() -> None:
    points = [(0.0, 5.0), (1.0, 5.0), (2.0, 5.0)]
    fitted = linear_trend(points)
    assert fitted is not None
    assert fitted.slope == pytest.approx(0.0)
    assert fitted.r_squared == pytest.approx(1.0)


def test_linear_trend_insufficient_points() -> None:
    assert linear_trend([]) is None
    assert linear_trend([(0.0, 1.0)]) is None


def test_rate_of_change_converts_units() -> None:
    points = [(0.0, 0.0), (3600.0, 10.0)]  # 10 units over 1 hour
    fitted = linear_trend(points)
    assert rate_of_change(fitted, seconds_per_unit=3600.0) == pytest.approx(10.0)
    assert rate_of_change(None) is None


def test_trend_confidence_matches_r_squared() -> None:
    points = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    fitted = linear_trend(points)
    assert trend_confidence(fitted) == pytest.approx(1.0)
    assert trend_confidence(None) is None


@pytest.mark.parametrize(
    "change_percent,expected",
    [
        (None, TrendDirection.INSUFFICIENT_DATA),
        (0.5, TrendDirection.STABLE),
        (-0.5, TrendDirection.STABLE),
        (5.0, TrendDirection.INCREASING),
        (-5.0, TrendDirection.DECREASING),
        (20.0, TrendDirection.RAPID_INCREASE),
        (-20.0, TrendDirection.RAPID_DECREASE),
    ],
)
def test_classify_trend(change_percent, expected) -> None:
    assert classify_trend(change_percent) == expected


def test_trend_percentage_delegates_to_percent_change() -> None:
    assert trend_percentage(100.0, 110.0) == pytest.approx(10.0)
    assert trend_percentage(None, 1.0) is None
