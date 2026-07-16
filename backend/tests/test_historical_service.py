"""Unit tests for :class:`app.historical.service.HistoricalAnalyticsService`."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.analytics.config import get_analytics_config
from app.historical.aggregation import AggregationInterval
from app.historical.seasonal import SeasonalGroupBy
from app.historical.service import HistoricalAnalyticsService
from app.historical.trends import TrendDirection
from app.historical.utils import HistoryWindow
from app.serial.sensor_registry import get_sensor_registry
from app.utils.exceptions import BadRequestError, NotFoundError
from tests.historical_test_helpers import build_isolated_db_service, seed_time_series


def _service(db) -> HistoricalAnalyticsService:
    return HistoricalAnalyticsService(
        db=db, sensor_registry=get_sensor_registry(), analytics_config=get_analytics_config()
    )


def test_get_statistics_computes_expected_summary() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0, 8.0])
    service = _service(db)

    result = service.get_statistics(
        "dissolved_oxygen", start=start - timedelta(minutes=1), end=start + timedelta(days=1)
    )

    assert result.sample_count == 4
    assert result.minimum == 5.0
    assert result.maximum == 8.0
    assert result.average == pytest.approx(6.5)
    assert result.median == pytest.approx(6.5)
    assert result.first_value == 5.0
    assert result.last_value == 8.0
    assert result.percent_change == pytest.approx(60.0)
    assert result.source == "sensor"


def test_get_statistics_empty_range_returns_zero_sample_count() -> None:
    db = build_isolated_db_service()
    db.register_device("river-bot-01")
    db.register_sensor(sensor_key="dissolved_oxygen", display_name="Dissolved Oxygen")
    service = _service(db)

    result = service.get_statistics("dissolved_oxygen", window=HistoryWindow.DAY)
    assert result.sample_count == 0
    assert result.minimum is None
    assert result.percent_change is None


def test_get_statistics_unknown_parameter_raises() -> None:
    db = build_isolated_db_service()
    service = _service(db)
    with pytest.raises(NotFoundError):
        service.get_statistics("not_a_real_parameter", window=HistoryWindow.DAY)


def test_get_trends_classifies_increasing_series() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0, 8.0, 9.0])
    service = _service(db)

    result = service.get_trends(
        "dissolved_oxygen", start=start - timedelta(minutes=1), end=start + timedelta(days=1)
    )
    assert result.direction in (TrendDirection.INCREASING, TrendDirection.RAPID_INCREASE)
    assert result.trend_percentage == pytest.approx(80.0)
    assert result.trend_confidence == pytest.approx(1.0)
    assert result.slope is not None and result.slope > 0


def test_get_trends_stable_series() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [7.0, 7.0, 7.0, 7.0])
    service = _service(db)

    result = service.get_trends(
        "dissolved_oxygen", start=start - timedelta(minutes=1), end=start + timedelta(days=1)
    )
    assert result.direction == TrendDirection.STABLE


def test_get_trends_no_data_is_insufficient() -> None:
    db = build_isolated_db_service()
    db.register_device("river-bot-01")
    db.register_sensor(sensor_key="dissolved_oxygen", display_name="Dissolved Oxygen")
    service = _service(db)

    result = service.get_trends("dissolved_oxygen", window=HistoryWindow.DAY)
    assert result.direction == TrendDirection.INSUFFICIENT_DATA


def test_get_seasonal_groups_by_hour() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0])
    service = _service(db)

    result = service.get_seasonal(
        "dissolved_oxygen",
        SeasonalGroupBy.HOUR,
        start=start - timedelta(minutes=1),
        end=start + timedelta(days=1),
    )
    assert result.group_by == SeasonalGroupBy.HOUR
    assert sum(g.count for g in result.groups) == 3


def test_get_aggregation_hourly_buckets() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0])
    service = _service(db)

    result = service.get_aggregation(
        "dissolved_oxygen",
        AggregationInterval.HOURLY,
        start=start - timedelta(minutes=1),
        end=start + timedelta(days=1),
    )
    assert result.interval == AggregationInterval.HOURLY
    assert sum(p.count for p in result.points) == 3


def test_get_comparison_correlates_two_parameters() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [1.0, 2.0, 3.0, 4.0])
    seed_time_series(
        db, "river-bot-01", "water_temperature", [10.0, 20.0, 30.0, 40.0], start=start
    )
    service = _service(db)

    result = service.get_comparison(
        "dissolved_oxygen",
        "water_temperature",
        start=start - timedelta(minutes=1),
        end=start + timedelta(days=1),
    )
    assert result.matched_points == 4
    assert result.correlation == pytest.approx(1.0)
    assert result.sample_count_a == 4
    assert result.sample_count_b == 4


def test_get_comparison_unknown_parameter_raises() -> None:
    db = build_isolated_db_service()
    seed_time_series(db, "river-bot-01", "dissolved_oxygen", [1.0, 2.0])
    service = _service(db)
    with pytest.raises(NotFoundError):
        service.get_comparison("dissolved_oxygen", "not_a_real_parameter", window=HistoryWindow.DAY)


def test_get_statistics_conflicting_time_params_raises() -> None:
    db = build_isolated_db_service()
    seed_time_series(db, "river-bot-01", "dissolved_oxygen", [1.0, 2.0])
    service = _service(db)
    with pytest.raises(BadRequestError):
        service.get_statistics(
            "dissolved_oxygen",
            window=HistoryWindow.DAY,
            start=service.db.get_latest_readings(limit=1)[0].timestamp,
            end=service.db.get_latest_readings(limit=1)[0].timestamp,
        )
