"""Tests for ``GET /api/v1/system/health`` and ``GET /api/v1/system/info``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.api_test_helpers import api_client  # noqa: F401  (fixture)


def test_system_health_returns_200(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/system/health")
    assert response.status_code == 200


def test_system_health_response_shape(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/system/health")
    body = response.json()

    assert body["success"] is True
    assert "message" in body
    assert "timestamp" in body["meta"]

    data = body["data"]
    assert data["application_status"] == "ok"
    assert data["database_status"] in ("ok", "degraded")
    assert data["serial_connection_status"] == "disconnected"
    assert data["version"] == settings.app_version
    assert data["uptime_seconds"] >= 0.0


def test_system_info_response_shape(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/system/info")
    assert response.status_code == 200
    body = response.json()

    data = body["data"]
    assert data["application_name"] == settings.app_name
    assert data["application_version"] == settings.app_version
    assert data["environment"] == settings.environment
    assert data["connected_device"] is None  # no serial acquisition running in tests
    assert data["firmware_version"] is None
    assert data["database_type"] == "postgresql"
    assert isinstance(data["configured_sensors"], list)
    assert len(data["configured_sensors"]) > 0
    assert any(sensor["sensor_name"] == "dissolved_oxygen" for sensor in data["configured_sensors"])
