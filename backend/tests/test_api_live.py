"""Tests for ``GET /api/v1/live/latest``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.api_test_helpers import api_client, seed_readings  # noqa: F401


def test_live_latest_returns_every_configured_sensor(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/live/latest")
    assert response.status_code == 200

    readings = response.json()["data"]["readings"]
    sensor_names = {r["sensor_name"] for r in readings}
    assert "dissolved_oxygen" in sensor_names
    assert "water_temperature" in sensor_names


def test_live_latest_no_data_sensor_reports_no_data(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/live/latest")
    readings = {r["sensor_name"]: r for r in response.json()["data"]["readings"]}

    reading = readings["dissolved_oxygen"]
    assert reading["value"] is None
    assert reading["timestamp"] is None
    assert reading["quality_status"] == "no_data"
    assert reading["validation_status"] == "no_data"


def test_live_latest_seeded_sensor_reports_good_quality(api_client: TestClient) -> None:
    settings = get_settings()
    seed_readings(api_client.db_service, "river-bot-01", {"dissolved_oxygen": 8.0})

    response = api_client.get(f"{settings.api_v1_prefix}/live/latest")
    readings = {r["sensor_name"]: r for r in response.json()["data"]["readings"]}

    reading = readings["dissolved_oxygen"]
    assert reading["value"] == 8.0
    assert reading["unit"] == "mg/L"
    assert reading["quality_status"] == "good"
    assert reading["validation_status"] == "valid"
    assert reading["timestamp"] is not None


def test_live_latest_out_of_range_value_reports_out_of_range(api_client: TestClient) -> None:
    settings = get_settings()
    # dissolved_oxygen's configured valid range is 0.0-20.0 mg/L.
    seed_readings(api_client.db_service, "river-bot-01", {"dissolved_oxygen": 999.0})

    response = api_client.get(f"{settings.api_v1_prefix}/live/latest")
    readings = {r["sensor_name"]: r for r in response.json()["data"]["readings"]}

    assert readings["dissolved_oxygen"]["quality_status"] == "out_of_range"


def test_live_latest_device_name_filter(api_client: TestClient) -> None:
    settings = get_settings()
    seed_readings(api_client.db_service, "river-bot-01", {"dissolved_oxygen": 8.0})

    response = api_client.get(
        f"{settings.api_v1_prefix}/live/latest", params={"device_name": "some-other-device"}
    )
    readings = {r["sensor_name"]: r for r in response.json()["data"]["readings"]}

    assert readings["dissolved_oxygen"]["quality_status"] == "no_data"


def test_live_latest_response_envelope(api_client: TestClient) -> None:
    settings = get_settings()
    response = api_client.get(f"{settings.api_v1_prefix}/live/latest")
    body = response.json()

    assert body["success"] is True
    assert "message" in body
    assert "timestamp" in body["meta"]
