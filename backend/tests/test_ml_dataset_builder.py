"""Unit tests for :mod:`app.ml.dataset_builder`."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from app.analytics.config import get_analytics_config
from app.ml.dataset_builder import DatasetBuilder
from app.serial.sensor_registry import get_sensor_registry
from app.utils.exceptions import BadRequestError, NotFoundError
from tests.historical_test_helpers import build_isolated_db_service, seed_time_series


def _builder(db) -> DatasetBuilder:
    return DatasetBuilder(db, get_sensor_registry(), get_analytics_config())


def test_build_requires_at_least_one_parameter() -> None:
    db = build_isolated_db_service()
    builder = _builder(db)
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    with pytest.raises(BadRequestError):
        builder.build([], now - timedelta(days=1), now)


def test_build_unknown_parameter_raises() -> None:
    db = build_isolated_db_service()
    builder = _builder(db)
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    with pytest.raises(NotFoundError):
        builder.build(["not_a_real_parameter"], now - timedelta(days=1), now)


def test_build_resamples_and_joins_parameters() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0, 8.0])
    seed_time_series(db, "river-bot-01", "water_temperature", [15.0, 16.0, 17.0, 18.0], start=start)
    builder = _builder(db)

    result = builder.build(
        ["dissolved_oxygen", "water_temperature"],
        start - timedelta(minutes=1),
        start + timedelta(hours=10),
        device_name="river-bot-01",
        resample_frequency="1h",
    )
    assert list(result.frame.columns) == ["dissolved_oxygen", "water_temperature"]
    assert result.display_names["dissolved_oxygen"]
    assert len(result.frame) > 0
    assert not result.frame["dissolved_oxygen"].isna().any()


def test_build_drops_columns_with_no_data() -> None:
    db = build_isolated_db_service()
    start = seed_time_series(db, "river-bot-01", "dissolved_oxygen", [5.0, 6.0, 7.0])
    db.register_sensor(sensor_key="water_temperature", display_name="Water Temperature")
    builder = _builder(db)

    result = builder.build(
        ["dissolved_oxygen", "water_temperature"],
        start - timedelta(minutes=1),
        start + timedelta(hours=5),
        device_name="river-bot-01",
    )
    assert "water_temperature" not in result.frame.columns
    assert "dissolved_oxygen" in result.frame.columns


def test_handle_missing_values_interpolate_fills_gaps() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
    df = pd.DataFrame({"x": [1.0, None, None, 4.0, 5.0]}, index=index)
    cleaned, dropped = DatasetBuilder.handle_missing_values(df, method="interpolate")
    assert dropped == 0
    assert not cleaned["x"].isna().any()
    assert cleaned["x"].iloc[1] == pytest.approx(2.0)


def test_handle_missing_values_drop() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame({"x": [1.0, None, 3.0]}, index=index)
    cleaned, dropped = DatasetBuilder.handle_missing_values(df, method="drop")
    assert dropped == 1
    assert len(cleaned) == 2


def test_handle_outliers_iqr_clips_extreme_values() -> None:
    index = pd.date_range("2026-01-01", periods=12, freq="1h", tz="UTC")
    values = [8.0, 9.0, 10.0, 11.0, 12.0, 9.0, 10.0, 11.0, 8.0, 12.0, 10.0, 1000.0]
    df = pd.DataFrame({"x": values}, index=index)
    cleaned = DatasetBuilder.handle_outliers(df, method="iqr", factor=1.5)
    assert cleaned["x"].max() < 1000.0


def test_handle_outliers_none_is_noop() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame({"x": [1.0, 2.0, 1000.0]}, index=index)
    cleaned = DatasetBuilder.handle_outliers(df, method="none")
    assert cleaned["x"].max() == 1000.0


def test_normalize_standard_scaler_zero_mean() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=index)
    normalized, scaler = DatasetBuilder.normalize(df, method="standard")
    assert scaler is not None
    assert normalized["x"].mean() == pytest.approx(0.0, abs=1e-9)


def test_normalize_none_is_noop() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]}, index=index)
    normalized, scaler = DatasetBuilder.normalize(df, method="none")
    assert scaler is None
    assert normalized["x"].tolist() == [1.0, 2.0, 3.0]
