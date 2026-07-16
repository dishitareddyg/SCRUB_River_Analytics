"""Unit tests for :mod:`app.historical.aggregation` and :mod:`app.historical.seasonal`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.historical.aggregation import AggregationInterval, aggregate_series
from app.historical.seasonal import SeasonalGroupBy, group_seasonal


def _dt(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def test_aggregate_series_hourly_groups_by_hour() -> None:
    points = [
        (_dt(2026, 1, 1, 3), 10.0),
        (datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc), 20.0),
        (_dt(2026, 1, 1, 4), 30.0),
    ]
    buckets = aggregate_series(points, AggregationInterval.HOURLY)
    assert len(buckets) == 2
    assert buckets[0].period_start == _dt(2026, 1, 1, 3)
    assert buckets[0].count == 2
    assert buckets[0].average == pytest.approx(15.0)
    assert buckets[1].count == 1
    assert buckets[1].average == pytest.approx(30.0)


def test_aggregate_series_daily_groups_by_day() -> None:
    points = [
        (_dt(2026, 1, 1, 1), 1.0),
        (_dt(2026, 1, 1, 23), 3.0),
        (_dt(2026, 1, 2, 0), 5.0),
    ]
    buckets = aggregate_series(points, AggregationInterval.DAILY)
    assert len(buckets) == 2
    assert buckets[0].count == 2
    assert buckets[0].average == pytest.approx(2.0)
    assert buckets[1].count == 1


def test_aggregate_series_weekly_starts_monday() -> None:
    # 2026-01-05 is a Monday.
    points = [(_dt(2026, 1, 7), 1.0), (_dt(2026, 1, 11), 2.0), (_dt(2026, 1, 12), 3.0)]
    buckets = aggregate_series(points, AggregationInterval.WEEKLY)
    assert buckets[0].period_start == _dt(2026, 1, 5)
    assert buckets[0].count == 2
    assert buckets[1].period_start == _dt(2026, 1, 12)
    assert buckets[1].count == 1


def test_aggregate_series_monthly_wraps_year() -> None:
    points = [(_dt(2025, 12, 15), 1.0), (_dt(2026, 1, 5), 2.0)]
    buckets = aggregate_series(points, AggregationInterval.MONTHLY)
    assert len(buckets) == 2
    assert buckets[0].period_start == _dt(2025, 12, 1)
    assert buckets[0].period_end == _dt(2026, 1, 1)
    assert buckets[1].period_start == _dt(2026, 1, 1)


def test_aggregate_series_drops_none_values() -> None:
    half_hour_later = _dt(2026, 1, 1) + timedelta(minutes=30)
    points = [(_dt(2026, 1, 1), 1.0), (half_hour_later, None)]
    buckets = aggregate_series(points, AggregationInterval.HOURLY)
    assert len(buckets) == 1
    assert buckets[0].count == 1


def test_aggregate_series_empty_input() -> None:
    assert aggregate_series([], AggregationInterval.DAILY) == []


def test_group_seasonal_by_hour() -> None:
    points = [
        (_dt(2026, 1, 1, 5), 10.0),
        (_dt(2026, 1, 2, 5), 20.0),
        (_dt(2026, 1, 3, 6), 30.0),
    ]
    groups = group_seasonal(points, SeasonalGroupBy.HOUR)
    by_key = {g.group_key: g for g in groups}
    assert by_key["05"].count == 2
    assert by_key["05"].average == pytest.approx(15.0)
    assert by_key["06"].count == 1


def test_group_seasonal_by_day_of_week() -> None:
    # 2026-01-05 is Monday.
    points = [(_dt(2026, 1, 5), 1.0), (_dt(2026, 1, 12), 3.0)]
    groups = group_seasonal(points, SeasonalGroupBy.DAY)
    assert groups[0].label == "Monday"
    assert groups[0].count == 2


def test_group_seasonal_by_month() -> None:
    points = [(_dt(2026, 3, 1), 1.0), (_dt(2026, 3, 15), 3.0), (_dt(2026, 4, 1), 5.0)]
    groups = group_seasonal(points, SeasonalGroupBy.MONTH)
    by_key = {g.group_key: g for g in groups}
    assert by_key["03"].label == "March"
    assert by_key["03"].count == 2
    assert by_key["04"].label == "April"


def test_group_seasonal_by_season() -> None:
    points = [(_dt(2026, 1, 1), 1.0), (_dt(2026, 12, 1), 2.0), (_dt(2026, 7, 1), 3.0)]
    groups = group_seasonal(points, SeasonalGroupBy.SEASON)
    labels = {g.label for g in groups}
    assert "Winter" in labels
    assert "Summer" in labels
    winter = next(g for g in groups if g.label == "Winter")
    assert winter.count == 2  # January and December


def test_group_seasonal_by_year() -> None:
    points = [(_dt(2025, 6, 1), 1.0), (_dt(2026, 6, 1), 2.0)]
    groups = group_seasonal(points, SeasonalGroupBy.YEAR)
    assert [g.label for g in groups] == ["2025", "2026"]


def test_group_seasonal_empty_input() -> None:
    assert group_seasonal([], SeasonalGroupBy.MONTH) == []
