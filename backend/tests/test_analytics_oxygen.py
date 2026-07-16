"""Tests for :mod:`app.analytics.oxygen`."""

from __future__ import annotations

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config


@pytest.fixture
def config() -> AnalyticsConfig:
    return base_analytics_config()


def test_oxygen_saturation_near_100_percent_at_table_value(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_saturation").calculate(
        {"dissolved_oxygen": 9.09, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(100.0, abs=1.0)


def test_oxygen_saturation_missing_required_input(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_saturation").calculate({"dissolved_oxygen": 8.0}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert "water_temperature" in result.missing_inputs


def test_oxygen_saturation_lower_confidence_without_optional_inputs(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_saturation").calculate(
        {"dissolved_oxygen": 8.0, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.warnings  # no conductivity / barometric_pressure supplied
    assert result.confidence == pytest.approx(0.6)


def test_oxygen_saturation_with_all_optional_inputs_has_fewer_warnings(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_saturation").calculate(
        {
            "dissolved_oxygen": 8.0,
            "water_temperature": 20.0,
            "conductivity": 400.0,
            "barometric_pressure": 1013.25,
        },
        config,
    )
    assert result.status is CalculationStatus.OK
    assert result.warnings == []
    assert result.confidence == pytest.approx(0.85)


def test_oxygen_saturation_supersaturated_exceeds_100_percent(config: AnalyticsConfig) -> None:
    """Supersaturation (e.g. algal photosynthesis) is a real, valid condition."""
    result = get_calculator("oxygen_saturation").calculate(
        {"dissolved_oxygen": 15.0, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value > 100.0


def test_oxygen_deficit_zero_when_at_saturation(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_deficit").calculate(
        {"dissolved_oxygen": 9.09, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(0.0, abs=0.05)


def test_oxygen_deficit_positive_when_undersaturated(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_deficit").calculate(
        {"dissolved_oxygen": 2.0, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0


def test_oxygen_deficit_extreme_temperature_out_of_range_warning(config: AnalyticsConfig) -> None:
    result = get_calculator("oxygen_deficit").calculate(
        {"dissolved_oxygen": 5.0, "water_temperature": 55.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert any("outside the documented valid range" in w for w in result.warnings)
