"""Unit tests for :mod:`app.historical.statistics`."""

from __future__ import annotations

import pytest

from app.historical import statistics as stats


def test_minimum_maximum_average_median() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert stats.minimum(values) == 1.0
    assert stats.maximum(values) == 5.0
    assert stats.average(values) == 3.0
    assert stats.median(values) == 3.0


def test_empty_values_return_none() -> None:
    assert stats.minimum([]) is None
    assert stats.maximum([]) is None
    assert stats.average([]) is None
    assert stats.median([]) is None
    assert stats.std_dev([]) is None
    assert stats.variance([]) is None
    assert stats.first_value([]) is None
    assert stats.last_value([]) is None


def test_std_dev_and_variance_single_value() -> None:
    assert stats.std_dev([5.0]) == 0.0
    assert stats.variance([5.0]) == 0.0


def test_std_dev_sample_vs_population() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    sample = stats.std_dev(values, sample=True)
    population = stats.std_dev(values, sample=False)
    assert sample is not None and population is not None
    assert sample > population


def test_percent_change() -> None:
    assert stats.percent_change(100.0, 150.0) == 50.0
    assert stats.percent_change(100.0, 50.0) == -50.0
    assert stats.percent_change(0.0, 50.0) is None
    assert stats.percent_change(None, 50.0) is None
    assert stats.percent_change(50.0, None) is None


def test_first_last_count() -> None:
    values = [10.0, 20.0, 30.0]
    assert stats.first_value(values) == 10.0
    assert stats.last_value(values) == 30.0
    assert stats.count(values) == 3


def test_missing_value_count() -> None:
    raw = [1.0, None, 2.0, None, None]
    assert stats.missing_value_count(raw) == 3
    assert stats.missing_value_count([1.0, 2.0]) == 0


def test_rolling_mean_alignment_and_values() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = stats.rolling_mean(values, window=3)
    assert result == [None, None, 2.0, 3.0, 4.0]


def test_rolling_mean_window_one_equals_values() -> None:
    values = [1.0, 2.0, 3.0]
    assert stats.rolling_mean(values, window=1) == values


def test_rolling_mean_invalid_window_raises() -> None:
    with pytest.raises(ValueError):
        stats.rolling_mean([1.0, 2.0], window=0)


def test_rolling_std_alignment() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    result = stats.rolling_std(values, window=2)
    assert result[0] is None
    assert result[1] == pytest.approx(stats.std_dev([1.0, 2.0]))
    assert result[2] == pytest.approx(stats.std_dev([2.0, 3.0]))
    assert result[3] == pytest.approx(stats.std_dev([3.0, 4.0]))


def test_moving_average_is_rolling_mean_alias() -> None:
    assert stats.moving_average is stats.rolling_mean
