"""Tests for :mod:`app.analytics.analytics_engine`."""

from __future__ import annotations

import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.result import CalculationStatus
from tests.analytics_test_helpers import build_populated_db_service, configured_analytics_config


def test_compute_reads_latest_reading_from_database() -> None:
    """compute() should resolve inputs from the DatabaseService, not require them inline."""
    db_service = build_populated_db_service("river-bot-01", {"conductivity": 1000.0})
    engine = AnalyticsEngine(database_service=db_service)

    result = engine.compute("tds")

    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(650.0)


def test_compute_not_computable_when_sensor_missing_from_db() -> None:
    db_service = build_populated_db_service("river-bot-01", {})
    engine = AnalyticsEngine(database_service=db_service)

    result = engine.compute("tds")

    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["conductivity"]


def test_compute_unknown_parameter_raises_key_error() -> None:
    db_service = build_populated_db_service("river-bot-01", {})
    engine = AnalyticsEngine(database_service=db_service)

    with pytest.raises(KeyError):
        engine.compute("not_a_real_parameter")


def test_compute_uses_most_recent_reading() -> None:
    """When multiple readings exist, the latest one should be used."""
    from datetime import datetime, timedelta, timezone

    db_service = build_populated_db_service("river-bot-01", {"conductivity": 100.0})
    db_service.save_sensor_reading(
        device_name="river-bot-01",
        sensor_key="conductivity",
        timestamp=datetime.now(timezone.utc) + timedelta(minutes=1),
        value=2000.0,
    )
    engine = AnalyticsEngine(database_service=db_service)

    result = engine.compute("tds")

    assert result.value == pytest.approx(2000.0 * 0.65)


def test_compute_all_returns_a_result_for_every_registered_parameter() -> None:
    from app.analytics.calculator_registry import registered_keys

    db_service = build_populated_db_service(
        "river-bot-01",
        {
            "conductivity": 500.0,
            "water_temperature": 18.0,
            "dissolved_oxygen": 8.0,
            "barometric_pressure": 1010.0,
            "river_depth": 1.2,
            "turbidity": 30.0,
        },
    )
    config = configured_analytics_config(bed_width_m=5.0, side_slope_h_per_v=2.0, channel_slope_m_per_m=0.001)
    engine = AnalyticsEngine(database_service=db_service, config=config)

    results = engine.compute_all()

    assert set(results.keys()) == set(registered_keys())
    for key in ("tds", "salinity", "oxygen_saturation", "oxygen_deficit", "water_density"):
        assert results[key].status is CalculationStatus.OK, f"{key} unexpectedly not OK: {results[key]}"
    for key in ("river_width", "cross_sectional_area", "flow_velocity", "river_discharge", "sediment_load"):
        assert results[key].status is CalculationStatus.OK, f"{key} unexpectedly not OK: {results[key]}"


def test_compute_all_with_no_data_is_not_computable_everywhere() -> None:
    db_service = build_populated_db_service("river-bot-01", {})
    engine = AnalyticsEngine(database_service=db_service)

    results = engine.compute_all()

    assert all(result.status is CalculationStatus.NOT_COMPUTABLE for result in results.values())


def test_available_parameters_lists_registered_keys() -> None:
    db_service = build_populated_db_service("river-bot-01", {})
    engine = AnalyticsEngine(database_service=db_service)

    parameters = engine.available_parameters()

    assert "tds" in parameters
    assert "river_discharge" in parameters
    assert parameters == sorted(parameters)


def test_sensor_key_map_override_repoints_input() -> None:
    """A deployment can repoint a calculator's input at a differently-named sensor."""
    db_service = build_populated_db_service("river-bot-01", {"conductivity_alt": 1000.0})
    engine = AnalyticsEngine(
        database_service=db_service, sensor_key_map={"conductivity": "conductivity_alt"}
    )

    result = engine.compute("tds")

    assert result.status is CalculationStatus.OK
    assert result.value == pytest.approx(650.0)


def test_compute_respects_device_name_filter() -> None:
    db_service = build_populated_db_service("river-bot-01", {"conductivity": 1000.0})
    engine = AnalyticsEngine(database_service=db_service)

    result = engine.compute("tds", device_name="a-different-device")

    assert result.status is CalculationStatus.NOT_COMPUTABLE
