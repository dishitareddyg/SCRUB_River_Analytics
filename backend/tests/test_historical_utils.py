"""Unit tests for :mod:`app.historical.utils`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.config import get_analytics_config
from app.serial.sensor_registry import get_sensor_registry
from app.utils.exceptions import BadRequestError, NotFoundError
from app.historical.utils import HistoryWindow, fetch_parameter_series, resolve_time_window
from tests.historical_test_helpers import build_isolated_db_service, seed_time_series


def test_resolve_time_window_shortcut() -> None:
    start, end = resolve_time_window(HistoryWindow.DAY, None, None)
    assert end - start == timedelta(days=1)


def test_resolve_time_window_custom_range() -> None:
    now = datetime.now(timezone.utc)
    start, end = resolve_time_window(None, now - timedelta(hours=2), now)
    assert end - start == timedelta(hours=2)


def test_resolve_time_window_defaults_to_day() -> None:
    start, end = resolve_time_window(None, None, None)
    assert end - start == timedelta(days=1)


def test_resolve_time_window_conflicting_params_raises() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(BadRequestError):
        resolve_time_window(HistoryWindow.DAY, now, now)


def test_resolve_time_window_partial_range_raises() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(BadRequestError):
        resolve_time_window(None, now, None)


def test_resolve_time_window_start_after_end_raises() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(BadRequestError):
        resolve_time_window(None, now, now - timedelta(hours=1))


def test_fetch_parameter_series_unknown_parameter_raises() -> None:
    db = build_isolated_db_service()
    registry = get_sensor_registry()
    config = get_analytics_config()
    now = datetime.now(timezone.utc)
    with pytest.raises(NotFoundError):
        fetch_parameter_series(db, registry, config, "not_a_real_parameter", now - timedelta(days=1), now)


def test_fetch_parameter_series_sensor_returns_points() -> None:
    db = build_isolated_db_service()
    registry = get_sensor_registry()
    config = get_analytics_config()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0])

    series = fetch_parameter_series(
        db, registry, config, "dissolved_oxygen", start - timedelta(minutes=1), start + timedelta(hours=5)
    )
    assert series.source == "sensor"
    assert series.anchor_sensor is None
    assert [v for _, v in series.points] == [5.0, 6.0, 7.0]
    assert series.missing_count == 0


def test_fetch_parameter_series_drops_missing_values() -> None:
    db = build_isolated_db_service()
    registry = get_sensor_registry()
    config = get_analytics_config()
    start = seed_time_series(
        db,
        "river-bot-01",
        "dissolved_oxygen",
        [5.0, 6.0, 7.0],
        value_fn=lambda i, v: None if i == 1 else v,
    )

    series = fetch_parameter_series(
        db, registry, config, "dissolved_oxygen", start - timedelta(minutes=1), start + timedelta(hours=5)
    )
    assert [v for _, v in series.points] == [5.0, 7.0]
    assert series.missing_count == 1


def test_fetch_parameter_series_analytics_uses_anchor_sensor() -> None:
    db = build_isolated_db_service()
    registry = get_sensor_registry()
    config = get_analytics_config()
    start = seed_time_series(db, "river-bot-01", "conductivity", [1000.0, 2000.0])

    series = fetch_parameter_series(
        db, registry, config, "tds", start - timedelta(minutes=1), start + timedelta(hours=5)
    )
    assert series.source == "analytics"
    assert series.anchor_sensor == "conductivity"
    assert [v for _, v in series.points] == [650.0, 1300.0]
