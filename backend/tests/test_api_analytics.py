"""Tests for ``GET /api/v1/analytics/latest``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.api_test_helpers import api_client, api_client_with_geometry, seed_readings  # noqa: F401


def test_analytics_latest_returns_every_registered_parameter(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/analytics/latest")
    assert response.status_code == 200

    results = response.json()["data"]["results"]
    keys = {r["parameter"] for r in results}
    assert "tds" in keys
    assert "salinity" in keys
    assert "river_discharge" in keys


def test_analytics_latest_computes_tds_from_conductivity(api_client: TestClient) -> None:
    settings = get_settings()
    seed_readings(api_client.db_service, "river-bot-01", {"conductivity": 1000.0})

    response = api_client.get(f"{settings.api_v1_prefix}/analytics/latest")
    results = {r["parameter"]: r for r in response.json()["data"]["results"]}

    tds = results["tds"]
    assert tds["status"] == "OK"
    assert tds["value"] == 650.0
    assert tds["unit"] == "mg/L"
    assert tds["display_name"] == "Total Dissolved Solids"
    assert tds["formula_used"]
    assert tds["reference"]


def test_analytics_latest_not_computable_without_inputs(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/analytics/latest")
    results = {r["parameter"]: r for r in response.json()["data"]["results"]}

    tds = results["tds"]
    assert tds["status"] == "NOT_COMPUTABLE"
    assert "conductivity" in tds["missing_inputs"]
    assert tds["value"] is None


def test_analytics_latest_geometry_not_computable_without_site_survey(api_client: TestClient) -> None:
    settings = get_settings()
    seed_readings(api_client.db_service, "river-bot-01", {"river_depth": 1.2})

    response = api_client.get(f"{settings.api_v1_prefix}/analytics/latest")
    results = {r["parameter"]: r for r in response.json()["data"]["results"]}

    assert results["river_width"]["status"] == "NOT_COMPUTABLE"


def test_analytics_latest_geometry_computable_with_configured_site(
    api_client_with_geometry: TestClient,
) -> None:
    settings = get_settings()
    seed_readings(api_client_with_geometry.db_service, "river-bot-01", {"river_depth": 1.2})

    response = api_client_with_geometry.get(f"{settings.api_v1_prefix}/analytics/latest")
    results = {r["parameter"]: r for r in response.json()["data"]["results"]}

    assert results["river_width"]["status"] == "OK"
    assert results["river_width"]["value"] == 9.8


def test_analytics_latest_device_name_filter(api_client: TestClient) -> None:
    settings = get_settings()
    seed_readings(api_client.db_service, "river-bot-01", {"conductivity": 1000.0})

    response = api_client.get(
        f"{settings.api_v1_prefix}/analytics/latest", params={"device_name": "some-other-device"}
    )
    results = {r["parameter"]: r for r in response.json()["data"]["results"]}

    assert results["tds"]["status"] == "NOT_COMPUTABLE"
