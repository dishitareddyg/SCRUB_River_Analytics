"""Tests for the ``/health`` endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import get_settings


def test_health_endpoint_returns_200(client: TestClient) -> None:
    """The health endpoint should always respond with HTTP 200."""
    settings = get_settings()
    response = client.get(f"{settings.api_v1_prefix}/health")
    assert response.status_code == 200


def test_health_endpoint_response_shape(client: TestClient) -> None:
    """The health endpoint should return the standard health envelope."""
    settings = get_settings()
    response = client.get(f"{settings.api_v1_prefix}/health")
    body = response.json()

    assert "success" in body
    assert "status" in body
    assert body["app_name"] == settings.app_name
    assert body["app_version"] == settings.app_version
    assert isinstance(body["components"], list)
    assert any(component["name"] == "database" for component in body["components"])
