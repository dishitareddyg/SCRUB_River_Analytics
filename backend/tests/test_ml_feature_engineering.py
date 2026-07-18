"""Unit tests for :mod:`app.ml.feature_engineering`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.feature_engineering import (
    FeatureConfig,
    add_calendar_features,
    add_change_feature,
    add_lag_features,
    add_rate_of_change,
    add_rolling_mean,
    add_rolling_std,
    build_features,
)


def _sample_frame(n: int = 30) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "dissolved_oxygen": np.linspace(5.0, 8.0, n),
            "conductivity": np.linspace(200.0, 260.0, n),
        },
        index=index,
    )


def test_add_rolling_mean_and_std() -> None:
    df = _sample_frame()
    mean = add_rolling_mean(df, "dissolved_oxygen", window=3)
    std = add_rolling_std(df, "dissolved_oxygen", window=3)
    assert mean.name == "dissolved_oxygen_roll_mean_3"
    assert std.name == "dissolved_oxygen_roll_std_3"
    assert mean.iloc[:2].isna().all()
    assert mean.iloc[2] == pytest.approx(df["dissolved_oxygen"].iloc[0:3].mean())


def test_add_rate_of_change() -> None:
    df = pd.DataFrame({"x": [10.0, 20.0, 10.0]}, index=pd.date_range("2026-01-01", periods=3, freq="1h"))
    roc = add_rate_of_change(df, "x")
    assert roc.name == "x_roc"
    assert roc.iloc[0] is None or pd.isna(roc.iloc[0])
    assert roc.iloc[1] == pytest.approx(100.0)
    assert roc.iloc[2] == pytest.approx(-50.0)


def test_add_lag_features() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}, index=pd.date_range("2026-01-01", periods=4, freq="1h"))
    lagged = add_lag_features(df, "x", lags=2)
    assert list(lagged.columns) == ["x_lag_1", "x_lag_2"]
    assert lagged["x_lag_1"].iloc[1] == 1.0
    assert lagged["x_lag_2"].iloc[2] == 1.0
    assert pd.isna(lagged["x_lag_1"].iloc[0])


def test_add_change_feature_uses_named_mapping() -> None:
    df = pd.DataFrame({"water_level": [1.0, 1.5, 1.2]}, index=pd.date_range("2026-01-01", periods=3, freq="1h"))
    change = add_change_feature(df, "water_level")
    assert change.name == "water_level_change"
    assert change.iloc[1] == pytest.approx(0.5)


def test_add_change_feature_generic_name_for_unmapped_column() -> None:
    df = pd.DataFrame({"orp": [100.0, 110.0]}, index=pd.date_range("2026-01-01", periods=2, freq="1h"))
    change = add_change_feature(df, "orp")
    assert change.name == "orp_change"


def test_add_calendar_features() -> None:
    df = _sample_frame(n=5)
    calendar = add_calendar_features(df)
    assert list(calendar.columns) == ["day_of_week", "month", "season"]
    assert calendar["month"].iloc[0] == 1
    assert calendar["season"].iloc[0] == 0  # January -> winter


def test_build_features_default_config_produces_expected_columns() -> None:
    df = _sample_frame(n=40)
    result = build_features(df)
    assert "dissolved_oxygen_roll_mean_3" in result.columns
    assert "dissolved_oxygen_lag_1" in result.columns
    assert "dissolved_oxygen_roc" in result.columns
    assert "do_change" in result.columns
    assert "conductivity_change" in result.columns
    assert "day_of_week" in result.columns
    # Leading NaN rows from the 24-row rolling window (min_periods=24,
    # so the first valid row is at position 23) should be dropped.
    assert not result.isna().any().any()
    assert len(result) == 40 - 23


def test_build_features_respects_target_columns_subset() -> None:
    df = _sample_frame(n=30)
    config = FeatureConfig(target_columns=["dissolved_oxygen"], roll_windows=[3], lag_counts=1)
    result = build_features(df, config)
    assert "dissolved_oxygen_roll_mean_3" in result.columns
    assert "conductivity_roll_mean_3" not in result.columns


def test_build_features_no_dropna_keeps_all_rows() -> None:
    df = _sample_frame(n=10)
    config = FeatureConfig(roll_windows=[3], lag_counts=1, dropna=False)
    result = build_features(df, config)
    assert len(result) == 10


def test_build_features_handles_inf_from_zero_baseline_pct_change() -> None:
    df = pd.DataFrame({"x": [0.0, 5.0, 10.0, 15.0]}, index=pd.date_range("2026-01-01", periods=4, freq="1h"))
    config = FeatureConfig(roll_windows=[], lag_counts=0, include_change_features=False, include_calendar_features=False)
    result = build_features(df, config)
    # No infinite values should leak through from pct_change() on a zero baseline.
    assert not np.isinf(result.to_numpy()).any()
