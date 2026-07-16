"""Tests for :mod:`app.analytics.hydrology`."""

from __future__ import annotations

import pytest

from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import base_analytics_config, configured_analytics_config


@pytest.fixture
def unconfigured() -> AnalyticsConfig:
    return base_analytics_config()


@pytest.fixture
def manning_config() -> AnalyticsConfig:
    return configured_analytics_config(
        bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001, velocity_equation="manning"
    )


@pytest.fixture
def chezy_config() -> AnalyticsConfig:
    return configured_analytics_config(
        bed_width_m=5.0,
        side_slope_h_per_v=2.0,
        channel_slope_m_per_m=0.001,
        velocity_equation="chezy",
        chezy_coefficient_c=45.0,
    )


def test_flow_velocity_not_computable_without_channel_slope() -> None:
    from dataclasses import replace

    config = configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0)
    config = replace(config, hydraulic=replace(config.hydraulic, channel_slope_m_per_m=None))
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_flow_velocity_manning(manning_config: AnalyticsConfig) -> None:
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, manning_config)
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0
    assert result.unit == "m/s"


def test_flow_velocity_chezy(chezy_config: AnalyticsConfig) -> None:
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, chezy_config)
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0


def test_flow_velocity_chezy_missing_coefficient_is_not_computable() -> None:
    config = configured_analytics_config(
        bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001, velocity_equation="chezy"
    )
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert "chezy_coefficient_c" in result.missing_inputs[0]


def test_flow_velocity_unrecognized_equation_is_not_computable() -> None:
    from dataclasses import replace

    config = configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001)
    config = replace(config, hydraulic=replace(config.hydraulic, velocity_equation="bogus"))
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_river_discharge_equals_velocity_times_area(manning_config: AnalyticsConfig) -> None:
    velocity = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, manning_config).value
    area = get_calculator("cross_sectional_area").calculate({"river_depth": 1.2}, manning_config).value
    discharge = get_calculator("river_discharge").calculate({"river_depth": 1.2}, manning_config).value
    assert discharge == pytest.approx(velocity * area)


def test_river_discharge_not_computable_without_geometry(unconfigured: AnalyticsConfig) -> None:
    result = get_calculator("river_discharge").calculate({"river_depth": 1.2}, unconfigured)
    assert result.status is CalculationStatus.NOT_COMPUTABLE


def test_flow_velocity_extreme_slope_numerical_stability(manning_config: AnalyticsConfig) -> None:
    from dataclasses import replace

    steep_config = replace(
        manning_config, hydraulic=replace(manning_config.hydraulic, channel_slope_m_per_m=0.5)
    )
    result = get_calculator("flow_velocity").calculate({"river_depth": 1.2}, steep_config)
    assert result.status is CalculationStatus.OK
    assert result.value > 0.0
