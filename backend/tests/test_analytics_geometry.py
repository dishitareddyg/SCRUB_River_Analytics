"""Tests for :mod:`app.analytics.geometry`."""

from __future__ import annotations

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config, configured_analytics_config

GEOMETRY_KEYS = [
    "river_width",
    "cross_sectional_area",
    "wetted_perimeter",
    "hydraulic_radius",
    "hydraulic_depth",
]


@pytest.fixture
def unconfigured() -> AnalyticsConfig:
    return base_analytics_config()


@pytest.fixture
def configured() -> AnalyticsConfig:
    return configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0)


@pytest.mark.parametrize("key", GEOMETRY_KEYS)
def test_geometry_not_computable_without_site_survey_config(key: str, unconfigured: AnalyticsConfig) -> None:
    """Every geometry calculator must fail safe when bed width/side slope aren't configured."""
    result = get_calculator(key).calculate({"river_depth": 1.5}, unconfigured)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs


@pytest.mark.parametrize("key", GEOMETRY_KEYS)
def test_geometry_not_computable_without_any_depth_reading(key: str, configured: AnalyticsConfig) -> None:
    """Every geometry calculator must fail safe when no depth sensor has data."""
    result = get_calculator(key).calculate({}, configured)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_river_width_uses_water_level_when_river_depth_missing(configured: AnalyticsConfig) -> None:
    result = get_calculator("river_width").calculate({"water_level": 1.2}, configured)
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(5.0 + 2 * 2.0 * 1.2)


def test_river_width_prefers_river_depth_over_water_level(configured: AnalyticsConfig) -> None:
    result = get_calculator("river_width").calculate(
        {"river_depth": 1.0, "water_level": 9.0}, configured
    )
    assert result.value == pytest.approx(5.0 + 2 * 2.0 * 1.0)


def test_cross_sectional_area_matches_hand_calculation(configured: AnalyticsConfig) -> None:
    result = get_calculator("cross_sectional_area").calculate({"river_depth": 1.2}, configured)
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx((5.0 + 2.0 * 1.2) * 1.2)


def test_wetted_perimeter_matches_hand_calculation(configured: AnalyticsConfig) -> None:
    import math

    result = get_calculator("wetted_perimeter").calculate({"river_depth": 1.2}, configured)
    expected = 5.0 + 2 * 1.2 * math.sqrt(1 + 2.0**2)
    assert result.value == pytest.approx(expected)


def test_hydraulic_radius_equals_area_over_perimeter(configured: AnalyticsConfig) -> None:
    area = get_calculator("cross_sectional_area").calculate({"river_depth": 1.2}, configured).value
    perimeter = get_calculator("wetted_perimeter").calculate({"river_depth": 1.2}, configured).value
    radius = get_calculator("hydraulic_radius").calculate({"river_depth": 1.2}, configured).value
    assert radius == pytest.approx(area / perimeter)


def test_hydraulic_depth_equals_area_over_top_width(configured: AnalyticsConfig) -> None:
    area = get_calculator("cross_sectional_area").calculate({"river_depth": 1.2}, configured).value
    width = get_calculator("river_width").calculate({"river_depth": 1.2}, configured).value
    depth = get_calculator("hydraulic_depth").calculate({"river_depth": 1.2}, configured).value
    assert depth == pytest.approx(area / width)


def test_river_width_zero_depth_boundary(configured: AnalyticsConfig) -> None:
    """Zero depth should return zero width (channel bed width) without error."""
    result = get_calculator("river_width").calculate({"river_depth": 0.0}, configured)
    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(5.0)


def test_hydraulic_radius_zero_perimeter_is_not_computable() -> None:
    """A degenerate (zero bed width, zero depth) channel means zero wetted perimeter; radius must fail safe, not divide by zero."""
    degenerate = configured_analytics_config(bed_width_m=0.0, side_slope_h_per_v=2.0)
    result = get_calculator("hydraulic_radius").calculate({"river_depth": 0.0}, degenerate)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_river_width_notes_missing_sonar_profiler(configured: AnalyticsConfig) -> None:
    result = get_calculator("river_width").calculate({"river_depth": 1.0}, configured)
    assert result.status is CalculationStatus.OK
    assert any("sonar" in w.lower() for w in result.warnings)
