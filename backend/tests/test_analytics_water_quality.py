"""Tests for :mod:`app.analytics.water_quality`."""

from __future__ import annotations

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config


@pytest.fixture
def config() -> AnalyticsConfig:
    return base_analytics_config()


def test_tds_valid_inputs(config: AnalyticsConfig) -> None:
    result = get_calculator("tds").calculate({"conductivity": 1000.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(650.0)
    assert result.unit == "mg/L"


def test_tds_missing_input(config: AnalyticsConfig) -> None:
    result = get_calculator("tds").calculate({}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["conductivity"]


def test_tds_boundary_zero(config: AnalyticsConfig) -> None:
    result = get_calculator("tds").calculate({"conductivity": 0.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value == 0.0


def test_tds_extreme_value_flags_out_of_range_warning(config: AnalyticsConfig) -> None:
    result = get_calculator("tds").calculate({"conductivity": 50000.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.warnings  # exceeds the documented 0-20000 uS/cm range


def test_salinity_valid_inputs(config: AnalyticsConfig) -> None:
    result = get_calculator("salinity").calculate(
        {"conductivity": 42914.0, "water_temperature": 15.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(35.0, abs=0.01)


def test_salinity_missing_one_of_two_required_inputs(config: AnalyticsConfig) -> None:
    result = get_calculator("salinity").calculate({"conductivity": 500.0}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["water_temperature"]


def test_salinity_freshwater_gets_low_confidence_warning(config: AnalyticsConfig) -> None:
    result = get_calculator("salinity").calculate(
        {"conductivity": 300.0, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value < 2.0
    assert result.confidence == pytest.approx(0.5)
    assert result.warnings


def test_salinity_numerical_stability_at_zero_conductivity(config: AnalyticsConfig) -> None:
    """Zero conductivity should not raise (e.g. divide-by-zero in R^0.5 terms)."""
    result = get_calculator("salinity").calculate(
        {"conductivity": 0.0, "water_temperature": 20.0}, config
    )
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(0.0, abs=0.5)
