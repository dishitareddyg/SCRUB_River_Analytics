"""Tests for the ``/history`` endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.api_test_helpers import api_client, seed_readings  # noqa: F401


def _seed_conductivity_series(client: TestClient, count: int = 5) -> None:
    client.db_service.register_device("river-bot-01")
    client.db_service.register_sensor(sensor_key="conductivity", display_name="Conductivity")
    base = datetime.now(timezone.utc) - timedelta(hours=count)
    for i in range(count):
        client.db_service.save_sensor_reading(
            device_name="river-bot-01",
            sensor_key="conductivity",
            timestamp=base + timedelta(hours=i),
            value=100.0 * (i + 1),
        )


# --- /history/sensor/{sensor_name} -----------------------------------------


def test_sensor_history_unknown_sensor_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/sensor/not_a_real_sensor")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert "not_a_real_sensor" in body["error"]["message"]


def test_sensor_history_defaults_to_last_day(api_client: TestClient) -> None:
    _seed_conductivity_series(api_client, count=3)
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/sensor/conductivity")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sensor_name"] == "conductivity"
    assert len(data["points"]) == 3
    # oldest first
    assert data["points"][0]["value"] == 100.0
    assert data["points"][-1]["value"] == 300.0


def test_sensor_history_empty_dataset_returns_200_with_empty_points(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity", params={"interval": "day"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["points"] == []


def test_sensor_history_interval_and_explicit_range_conflict_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity",
        params={"interval": "day", "start": now.isoformat(), "end": now.isoformat()},
    )
    assert response.status_code == 400


def test_sensor_history_start_without_end_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity",
        params={"start": now.isoformat()},
    )
    assert response.status_code == 400


def test_sensor_history_start_after_end_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity",
        params={"start": now.isoformat(), "end": (now - timedelta(hours=1)).isoformat()},
    )
    assert response.status_code == 400


def test_sensor_history_malformed_datetime_is_422(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity",
        params={"start": "not-a-date", "end": "also-not-a-date"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["type"] == "RequestValidationError"


def test_sensor_history_interval_latest_returns_single_point(api_client: TestClient) -> None:
    _seed_conductivity_series(api_client, count=3)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity", params={"interval": "latest"}
    )
    assert response.status_code == 200
    points = response.json()["data"]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 300.0


def test_sensor_history_pagination_fields_present(api_client: TestClient) -> None:
    _seed_conductivity_series(api_client, count=5)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/sensor/conductivity",
        params={"interval": "day", "page": 1, "page_size": 2},
    )
    data = response.json()["data"]
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] == 5
    assert data["total_pages"] == 3
    assert len(data["points"]) == 2


# --- /history/analytics/{parameter} -----------------------------------------


def test_analytics_history_unknown_parameter_returns_404(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/history/analytics/not_a_real_parameter")
    assert response.status_code == 404


def test_analytics_history_recomputes_tds_from_anchor_sensor(api_client: TestClient) -> None:
    _seed_conductivity_series(api_client, count=3)
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/analytics/tds", params={"interval": "day"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["parameter"] == "tds"
    assert data["anchor_sensor"] == "conductivity"
    assert len(data["points"]) == 3
    assert data["points"][0]["value"] == 100.0 * 0.65
    assert data["points"][0]["status"] == "OK"


def test_analytics_history_interval_latest_uses_engine_compute(api_client: TestClient) -> None:
    seed_readings(api_client.db_service, "river-bot-01", {"conductivity": 2000.0})
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/analytics/tds", params={"interval": "latest"}
    )
    assert response.status_code == 200
    points = response.json()["data"]["points"]
    assert len(points) == 1
    assert points[0]["value"] == 2000.0 * 0.65


def test_analytics_history_empty_dataset_returns_200_with_empty_points(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/analytics/tds", params={"interval": "day"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["points"] == []


def test_analytics_history_conflicting_range_is_400(api_client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    response = api_client.get(
        f"{settings.api_v1_prefix}/history/analytics/tds",
        params={"interval": "day", "start": now.isoformat(), "end": now.isoformat()},
    )
    assert response.status_code == 400
