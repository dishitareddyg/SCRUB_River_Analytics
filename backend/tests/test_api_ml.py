"""Tests for the AI Decision Support Engine endpoints (``/ml/predictions``, ``/anomalies``, ``/pollution``, ``/river-health``)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from tests.ml_test_helpers import ml_api_client, seed_ml_sensor_data  # noqa: F401


def test_predictions_unsupported_parameter_is_400(ml_api_client: TestClient) -> None:
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/predictions", params={"parameter": "not_a_real_parameter"}
    )
    assert response.status_code == 400


def test_predictions_insufficient_data_returns_200_with_status(ml_api_client: TestClient) -> None:
    seed_ml_sensor_data(ml_api_client.db_service, days=1)
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/predictions",
        params={"parameter": "dissolved_oxygen", "horizon": "next_hour", "device_name": "river-bot-01"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "insufficient_data"


def test_predictions_ok_returns_forecast(ml_api_client: TestClient) -> None:
    seed_ml_sensor_data(ml_api_client.db_service, days=15)
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/predictions",
        params={"parameter": "dissolved_oxygen", "horizon": "next_hour", "device_name": "river-bot-01"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["predicted_value"] is not None
    assert data["model"]["model_name"] == "trend_dissolved_oxygen_next_hour"


def test_anomalies_ok_returns_score(ml_api_client: TestClient) -> None:
    seed_ml_sensor_data(ml_api_client.db_service, days=15)
    settings = get_settings()
    response = ml_api_client.get(f"{settings.api_v1_prefix}/ml/anomalies", params={"device_name": "river-bot-01"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert 0.0 <= data["anomaly_score"] <= 1.0


def test_anomalies_insufficient_data(ml_api_client: TestClient) -> None:
    ml_api_client.db_service.register_device("river-bot-01")
    settings = get_settings()
    response = ml_api_client.get(f"{settings.api_v1_prefix}/ml/anomalies", params={"device_name": "river-bot-01"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "insufficient_data"


def test_pollution_returns_probability_distribution(ml_api_client: TestClient) -> None:
    seed_ml_sensor_data(ml_api_client.db_service, days=5)
    settings = get_settings()
    response = ml_api_client.get(f"{settings.api_v1_prefix}/ml/pollution", params={"device_name": "river-bot-01"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert abs(sum(data["probabilities"].values()) - 1.0) < 1e-2


def test_pollution_insufficient_data(ml_api_client: TestClient) -> None:
    ml_api_client.db_service.register_device("river-bot-01")
    settings = get_settings()
    response = ml_api_client.get(f"{settings.api_v1_prefix}/ml/pollution", params={"device_name": "river-bot-01"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "insufficient_data"


def test_river_health_returns_forecast(ml_api_client: TestClient) -> None:
    seed_ml_sensor_data(ml_api_client.db_service, days=10)
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/river-health", params={"horizon": "next_day", "device_name": "river-bot-01"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["health_category"] in ("excellent", "good", "fair", "poor", "critical")


def test_river_health_insufficient_data(ml_api_client: TestClient) -> None:
    ml_api_client.db_service.register_device("river-bot-01")
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/river-health", params={"device_name": "river-bot-01"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "insufficient_data"


def test_predictions_invalid_horizon_is_422(ml_api_client: TestClient) -> None:
    settings = get_settings()
    response = ml_api_client.get(
        f"{settings.api_v1_prefix}/ml/predictions",
        params={"parameter": "dissolved_oxygen", "horizon": "next_century"},
    )
    assert response.status_code == 422
