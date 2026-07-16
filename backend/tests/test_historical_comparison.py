"""Unit tests for :mod:`app.historical.comparison`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.historical.comparison import compare_series, pearson_correlation


def _dt(hours: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hours)


def test_pearson_correlation_perfect_positive() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    assert pearson_correlation(xs, ys) == pytest.approx(1.0)


def test_pearson_correlation_perfect_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [8.0, 6.0, 4.0, 2.0]
    assert pearson_correlation(xs, ys) == pytest.approx(-1.0)


def test_pearson_correlation_constant_series_is_none() -> None:
    assert pearson_correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_pearson_correlation_insufficient_points() -> None:
    assert pearson_correlation([1.0], [1.0]) is None
    assert pearson_correlation([], []) is None


def test_compare_series_aligns_and_correlates() -> None:
    points_a = [(_dt(i), float(i)) for i in range(10)]
    points_b = [(_dt(i), float(i) * 2.0) for i in range(10)]
    result = compare_series(points_a, points_b)
    assert result.matched_points == 10
    assert result.correlation == pytest.approx(1.0)
    assert result.parameter_a.count == 10
    assert result.parameter_b.count == 10
    assert result.parameter_a.average == pytest.approx(4.5)


def test_compare_series_no_overlap() -> None:
    points_a = [(_dt(i), 1.0) for i in range(3)]
    points_b = [(_dt(i + 1000), 2.0) for i in range(3)]
    result = compare_series(points_a, points_b)
    assert result.matched_points == 0
    assert result.correlation is None
    assert result.parameter_a.count == 3
    assert result.parameter_b.count == 3


def test_compare_series_empty_inputs() -> None:
    result = compare_series([], [])
    assert result.matched_points == 0
    assert result.correlation is None
    assert result.parameter_a.count == 0
    assert result.parameter_a.average is None
