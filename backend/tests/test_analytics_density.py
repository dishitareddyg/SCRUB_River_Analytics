"""Tests for :mod:`app.analytics.density`."""

from __future__ import annotations

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config


@pytest.fixture
def config() -> AnalyticsConfig:
    return base_analytics_config()


def test_water_density_pure_water_at_4c(config: AnalyticsConfig) -> None:
    result = get_calculator("water_density").calculate({"water_temperature": 4.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(999.97, abs=0.01)
    assert result.warnings  # no conductivity supplied -> freshwater assumption warning


def test_water_density_missing_required_input(config: AnalyticsConfig) -> None:
    result = get_calculator("water_density").calculate({}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["water_temperature"]


def test_water_density_with_salinity_correction_is_higher(config: AnalyticsConfig) -> None:
    fresh = get_calculator("water_density").calculate({"water_temperature": 20.0}, config)
    saline = get_calculator("water_density").calculate(
        {"water_temperature": 20.0, "conductivity": 20000.0}, config
    )
    assert saline.value > fresh.value
    assert saline.warnings == []


def test_water_density_extreme_temperature(config: AnalyticsConfig) -> None:
    """Numerical stability check at an extreme but non-crashing temperature."""
    result = get_calculator("water_density").calculate({"water_temperature": 99.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0
