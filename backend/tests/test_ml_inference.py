"""Unit tests for :class:`app.ml.inference.MLInferenceService`."""

from __future__ import annotations

import pytest

from app.analytics.config import get_analytics_config
from app.ml.inference import MLInferenceService
from app.ml.model_manager import ModelManager
from app.ml.trainer import TrainingPipeline
from app.ml.utils import MLStatus, PredictionHorizon
from app.serial.sensor_registry import get_sensor_registry
from app.utils.exceptions import BadRequestError
from tests.historical_test_helpers import build_isolated_db_service
from tests.ml_test_helpers import build_ml_settings, seed_ml_sensor_data


def _service(db, tmp_path, min_samples: int = 20) -> MLInferenceService:
    settings = build_ml_settings(str(tmp_path), min_training_samples=min_samples)
    registry = get_sensor_registry()
    config = get_analytics_config()
    manager = ModelManager(str(tmp_path))
    pipeline = TrainingPipeline(db, registry, config, manager, settings)
    return MLInferenceService(db, registry, config, manager, settings, pipeline=pipeline)


def test_predict_unsupported_parameter_raises(tmp_path) -> None:
    db = build_isolated_db_service()
    service = _service(db, tmp_path)
    with pytest.raises(BadRequestError):
        service.predict("not_a_real_parameter", PredictionHorizon.NEXT_HOUR)


def test_predict_insufficient_data_returns_status(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=2)
    service = _service(db, tmp_path, min_samples=1000)

    result = service.predict("dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01")
    assert result.status == MLStatus.INSUFFICIENT_DATA
    assert result.predicted_value is None


def test_predict_trains_on_first_call_and_caches_on_second(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=15)
    service = _service(db, tmp_path, min_samples=20)

    first = service.predict("dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01")
    assert first.status == MLStatus.OK
    assert first.model.freshly_trained is True
    assert first.predicted_value is not None
    assert first.confidence_interval_lower <= first.predicted_value <= first.confidence_interval_upper

    second = service.predict("dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01")
    assert second.status == MLStatus.OK
    assert second.model.freshly_trained is False
    assert second.model.version == first.model.version


def test_detect_anomaly_insufficient_data_returns_status(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=1)
    service = _service(db, tmp_path, min_samples=1000)

    result = service.detect_anomaly(device_name="river-bot-01")
    assert result.status == MLStatus.INSUFFICIENT_DATA


def test_detect_anomaly_ok_returns_score_and_label(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=15)
    service = _service(db, tmp_path, min_samples=20)

    result = service.detect_anomaly(device_name="river-bot-01")
    assert result.status == MLStatus.OK
    assert 0.0 <= result.anomaly_score <= 1.0
    assert isinstance(result.is_anomaly, bool)
    assert len(result.evaluated_parameters) > 0


def test_classify_pollution_no_data_is_insufficient(tmp_path) -> None:
    db = build_isolated_db_service()
    db.register_device("river-bot-01")
    service = _service(db, tmp_path)

    result = service.classify_pollution(device_name="river-bot-01")
    assert result.status == MLStatus.INSUFFICIENT_DATA


def test_classify_pollution_with_data_returns_distribution(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=5)
    service = _service(db, tmp_path)

    result = service.classify_pollution(device_name="river-bot-01")
    assert result.status == MLStatus.OK
    assert result.most_likely_source is not None
    assert sum(result.probabilities.values()) == pytest.approx(1.0, abs=1e-2)


def test_forecast_river_health_insufficient_data(tmp_path) -> None:
    db = build_isolated_db_service()
    db.register_device("river-bot-01")
    service = _service(db, tmp_path)

    result = service.forecast_river_health(PredictionHorizon.NEXT_DAY, device_name="river-bot-01")
    assert result.status == MLStatus.INSUFFICIENT_DATA


def test_forecast_river_health_with_data_returns_score(tmp_path) -> None:
    db = build_isolated_db_service()
    seed_ml_sensor_data(db, days=10)
    service = _service(db, tmp_path)

    result = service.forecast_river_health(PredictionHorizon.NEXT_DAY, device_name="river-bot-01")
    assert result.status == MLStatus.OK
    assert result.current_score is not None
    assert 0.0 <= result.predicted_score <= 100.0
    assert result.health_category is not None
