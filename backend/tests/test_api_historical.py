"""Tests for the historical analytics endpoints (``/history/statistics``, ``/trends``, ``/seasonal``, ``/compare``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.api_test_helpers import api_client  # noqa: F401


def _seed_series(client: TestClient, sensor_key: str = "dissolved_oxygen", count: int = 6) -> datetime:
    client.db_service.register_device("river-bot-01")
    client.db_service.register_sensor(sensor_key=sensor_key, display_name=sensor_key, unit="mg/L")
    base = datetime.now(timezone.utc) - timedelta(hours=count)
    for i in range(count):
        client.db_service.save_sensor_reading(
            device_name="river-bot-01",
            sensor_key=sensor_key,
            timestamp=base + timedelta(hours=i),
            value=float(i + 1),
        )
    return base


# --- /history/statistics/{parameter} ----------------------------------------


def test_statistics_unknown_parameter_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/statistics/not_a_real_parameter")
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_statistics_returns_expected_summary(api_client: TestClient) -> None:
    _seed_series(api_client, count=4)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/statistics/dissolved_oxygen", params={"window": "day"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sample_count"] == 4
    assert data["minimum"] == 1.0
    assert data["maximum"] == 4.0
    assert data["average"] == 2.5
    assert data["first_value"] == 1.0
    assert data["last_value"] == 4.0


def test_statistics_empty_dataset_returns_200_with_zero_samples(api_client: TestClient) -> None:
    api_client.db_service.register_device("river-bot-01")
    api_client.db_service.register_sensor(sensor_key="dissolved_oxygen", display_name="Dissolved Oxygen")
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/statistics/dissolved_oxygen", params={"window": "day"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["sample_count"] == 0


def test_statistics_window_and_range_conflict_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/statistics/dissolved_oxygen",
        params={"window": "day", "start": now.isoformat(), "end": now.isoformat()},
    )
    assert response.status_code == 400


def test_statistics_start_after_end_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/statistics/dissolved_oxygen",
        params={"start": now.isoformat(), "end": (now - timedelta(hours=1)).isoformat()},
    )
    assert response.status_code == 400


def test_statistics_supports_analytics_parameter(api_client: TestClient) -> None:
    _seed_series(api_client, sensor_key="conductivity", count=3)
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/statistics/tds", params={"window": "day"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "analytics"
    assert data["anchor_sensor"] == "conductivity"
    assert data["sample_count"] == 3


# --- /history/trends/{parameter} --------------------------------------------


def test_trends_unknown_parameter_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/trends/not_a_real_parameter")
    assert response.status_code == 404


def test_trends_increasing_series(api_client: TestClient) -> None:
    _seed_series(api_client, count=5)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/trends/dissolved_oxygen", params={"window": "day"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["direction"] in ("increasing", "rapid_increase")
    assert data["trend_percentage"] > 0


def test_trends_no_data_is_insufficient(api_client: TestClient) -> None:
    api_client.db_service.register_device("river-bot-01")
    api_client.db_service.register_sensor(sensor_key="dissolved_oxygen", display_name="Dissolved Oxygen")
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/trends/dissolved_oxygen", params={"window": "day"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["direction"] == "insufficient_data"


# --- /history/seasonal/{parameter} ------------------------------------------


def test_seasonal_unknown_parameter_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/seasonal/not_a_real_parameter")
    assert response.status_code == 404


def test_seasonal_groups_by_hour(api_client: TestClient) -> None:
    _seed_series(api_client, count=5)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/seasonal/dissolved_oxygen",
        params={"window": "day", "group_by": "hour"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["group_by"] == "hour"
    assert sum(g["count"] for g in data["groups"]) == 5


def test_seasonal_defaults_to_month_grouping(api_client: TestClient) -> None:
    _seed_series(api_client, count=2)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/seasonal/dissolved_oxygen", params={"window": "day"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["group_by"] == "month"


# --- /history/compare --------------------------------------------------------


def test_compare_unknown_parameter_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/compare",
        params={"parameter_a": "dissolved_oxygen", "parameter_b": "not_a_real_parameter"},
    )
    assert response.status_code == 404


def test_compare_same_parameter_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/compare",
        params={"parameter_a": "dissolved_oxygen", "parameter_b": "dissolved_oxygen"},
    )
    assert response.status_code == 400


def test_compare_two_sensors(api_client: TestClient) -> None:
    base = _seed_series(api_client, sensor_key="dissolved_oxygen", count=4)
    api_client.db_service.register_sensor(sensor_key="water_temperature", display_name="Water Temperature")
    for i in range(4):
        api_client.db_service.save_sensor_reading(
            device_name="river-bot-01",
            sensor_key="water_temperature",
            timestamp=base + timedelta(hours=i),
            value=float(i + 1) * 2.0,
        )
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/compare",
        params={"parameter_a": "dissolved_oxygen", "parameter_b": "water_temperature", "window": "day"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["matched_points"] == 4
    assert data["correlation"] == pytest.approx(1.0)
