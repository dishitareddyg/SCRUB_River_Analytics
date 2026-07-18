"""Unit tests for :mod:`app.ml.trainer`."""

from __future__ import annotations

import pytest

from app.analytics.config import get_analytics_config
from app.ml.model_manager import ModelManager
from app.ml.trainer import ANOMALY_MODEL_NAME, TrainingPipeline, trend_model_name
from app.ml.utils import InsufficientDataError, PredictionHorizon
from app.serial.sensor_registry import get_sensor_registry
from tests.historical_test_helpers import build_isolated_db_service
from tests.ml_test_helpers import build_ml_settings, seed_ml_sensor_data


def _pipeline(db, tmp_path, min_samples: int = 20) -> TrainingPipeline:
    settings = build_ml_settings(str(tmp_path), min_training_samples=min_samples)
    return TrainingPipeline(
        db, get_sensor_registry(), get_analytics_config(), ModelManager(str(tmp_path)), settings
    )


def test_trend_model_name_format() -> None:
    assert trend_model_name("dissolved_oxygen", PredictionHorizon.NEXT_HOUR) == "trend_dissolved_oxygen_next_hour"


def test_train_anomaly_detector_insufficient_data_raises(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=1000)
    seed_ml_sensor_data(db, days=2)
    with pytest.raises(InsufficientDataError):
        pipeline.train_anomaly_detector(device_name="river-bot-01")


def test_train_anomaly_detector_saves_a_model(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=20)
    seed_ml_sensor_data(db, days=15)

    metadata = pipeline.train_anomaly_detector(device_name="river-bot-01")
    assert metadata.model_name == ANOMALY_MODEL_NAME
    assert metadata.algorithm == "isolation_forest"
    assert pipeline.model_manager.has_model(ANOMALY_MODEL_NAME)


def test_train_trend_predictor_insufficient_data_raises(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=1000)
    seed_ml_sensor_data(db, days=2)
    with pytest.raises(InsufficientDataError):
        pipeline.train_trend_predictor("dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01")


def test_train_trend_predictor_saves_a_model_with_metrics(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=20)
    seed_ml_sensor_data(db, days=15)

    metadata = pipeline.train_trend_predictor(
        "dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01"
    )
    assert metadata.model_name == "trend_dissolved_oxygen_next_hour"
    assert set(metadata.metrics.keys()) == {"mae", "rmse", "r2"}
    assert metadata.training_rows > 0


def test_prepare_trend_dataset_unknown_target_raises_insufficient_data(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=20)
    seed_ml_sensor_data(db, days=5, sensor_keys=["conductivity"])
    with pytest.raises(InsufficientDataError):
        pipeline.prepare_trend_dataset("dissolved_oxygen", PredictionHorizon.NEXT_HOUR, device_name="river-bot-01")


def test_train_all_reports_skipped_models_without_raising(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=1000)
    seed_ml_sensor_data(db, days=2)

    summary = pipeline.train_all(parameters=["dissolved_oxygen"], horizons=[PredictionHorizon.NEXT_HOUR])
    assert summary.anomaly_model is None
    assert summary.trend_models == {}
    assert ANOMALY_MODEL_NAME in summary.skipped
    assert "trend_dissolved_oxygen_next_hour" in summary.skipped


def test_train_all_trains_every_requested_model(tmp_path) -> None:
    db = build_isolated_db_service()
    pipeline = _pipeline(db, tmp_path, min_samples=20)
    seed_ml_sensor_data(db, days=15)

    summary = pipeline.train_all(
        parameters=["dissolved_oxygen", "conductivity"],
        horizons=[PredictionHorizon.NEXT_HOUR, PredictionHorizon.NEXT_DAY],
        device_name="river-bot-01",
    )
    assert summary.anomaly_model is not None
    assert len(summary.trend_models) == 4
    assert summary.skipped == {}
