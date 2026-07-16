"""Tests for :mod:`app.analytics.sediment`."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config, configured_analytics_config


@pytest.fixture
def unconfigured() -> AnalyticsConfig:
    return base_analytics_config()


@pytest.fixture
def turbidity_config() -> AnalyticsConfig:
    config = configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001)
    return replace(config, sediment=replace(config.sediment, method="turbidity_surrogate"))


@pytest.fixture
def rating_curve_config() -> AnalyticsConfig:
    config = configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001)
    return replace(config, sediment=replace(config.sediment, method="discharge_rating_curve"))


def test_sediment_load_not_computable_without_geometry(unconfigured: AnalyticsConfig) -> None:
    result = get_calculator("sediment_load").calculate({"river_depth": 1.2, "turbidity": 50.0}, unconfigured)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_sediment_load_turbidity_surrogate_requires_turbidity(turbidity_config: AnalyticsConfig) -> None:
    result = get_calculator("sediment_load").calculate({"river_depth": 1.2}, turbidity_config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["turbidity"]


def test_sediment_load_turbidity_surrogate_valid(turbidity_config: AnalyticsConfig) -> None:
    result = get_calculator("sediment_load").calculate(
        {"river_depth": 1.2, "turbidity": 50.0}, turbidity_config
    )
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0
    assert result.unit == "tons/day"


def test_sediment_load_discharge_rating_curve_does_not_require_turbidity(
    rating_curve_config: AnalyticsConfig,
) -> None:
    result = get_calculator("sediment_load").calculate({"river_depth": 1.2}, rating_curve_config)
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0
    assert any("no turbidity surrogate" in w.lower() for w in result.warnings)


def test_sediment_load_increases_with_turbidity(turbidity_config: AnalyticsConfig) -> None:
    low = get_calculator("sediment_load").calculate(
        {"river_depth": 1.2, "turbidity": 10.0}, turbidity_config
    )
    high = get_calculator("sediment_load").calculate(
        {"river_depth": 1.2, "turbidity": 500.0}, turbidity_config
    )
    assert high.value > low.value


def test_sediment_load_zero_turbidity_boundary(turbidity_config: AnalyticsConfig) -> None:
    result = get_calculator("sediment_load").calculate(
        {"river_depth": 1.2, "turbidity": 0.0}, turbidity_config
    )
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(0.0)


def test_sediment_load_unrecognized_method_is_not_computable(turbidity_config: AnalyticsConfig) -> None:
    bad_config = replace(turbidity_config, sediment=replace(turbidity_config.sediment, method="bogus"))
    result = get_calculator("sediment_load").calculate(
        {"river_depth": 1.2, "turbidity": 50.0}, bad_config
    )
    assert result.status is CalculationStatus.NOT_COMPUTABLE
