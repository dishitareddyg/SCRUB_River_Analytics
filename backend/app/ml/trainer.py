"""The offline (or on-demand) training pipeline.

:class:`TrainingPipeline` ties together every stage - dataset
building, feature engineering, model training, evaluation, and
persistence - for the two model families that actually need training
(:class:`~app.ml.anomaly_detector.AnomalyDetector` and
:class:`~app.ml.trend_predictor.TrendPredictor`; the pollution
classifier is rule-based and the river health forecast is computed
directly from a linear trend, neither needs a persisted model - see
``app/ml/pollution_classifier.py`` and
``app/ml/river_health_predictor.py``).

:class:`~app.ml.inference.MLInferenceService` also uses this class's
``prepare_*`` methods directly (not just ``train_*``) so the exact
same feature space used to train a model is used to build the current
snapshot it predicts from - one implementation, not two copies that
could drift apart.

Runnable directly for an initial/offline training pass::

    python -m app.ml.trainer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.config.settings import Settings, get_settings
from app.database.service import DatabaseService, get_database_service
from app.ml.anomaly_detector import AnomalyDetector
from app.ml.dataset_builder import DatasetBuilder
from app.ml.feature_engineering import FeatureConfig, build_features
from app.ml.model_manager import ModelManager, ModelMetadata
from app.ml.trend_predictor import TrendPredictor
from app.ml.utils import (
    DEFAULT_MONITORING_PARAMETERS,
    DEFAULT_TREND_PARAMETERS,
    HORIZON_STEPS,
    InsufficientDataError,
    PredictionHorizon,
)
from app.serial.sensor_registry import SensorRegistry, get_sensor_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)

ANOMALY_MODEL_NAME = "anomaly_detector"


def trend_model_name(parameter: str, horizon: PredictionHorizon) -> str:
    """Build the logical model name used to save/load a trend predictor.

    Args:
        parameter: The forecast parameter's key.
        horizon: The forecast horizon.

    Returns:
        A model name like ``"trend_dissolved_oxygen_next_hour"``.
    """
    return f"trend_{parameter}_{horizon.value}"


@dataclass
class TrainingSummary:
    """The result of a :meth:`TrainingPipeline.train_all` run.

    Attributes:
        anomaly_model: Metadata for the trained anomaly detector, or
            ``None`` if training was skipped (insufficient data).
        trend_models: Trend predictor metadata, keyed by model name.
        skipped: Model names skipped due to insufficient data, mapped
            to a short reason.
    """

    anomaly_model: Optional[ModelMetadata] = None
    trend_models: Dict[str, ModelMetadata] = field(default_factory=dict)
    skipped: Dict[str, str] = field(default_factory=dict)


class TrainingPipeline:
    """Builds datasets, trains models, evaluates them, and saves them.

    Every dependency is injected through the constructor (Dependency
    Injection coding standard, matching every other service in this
    codebase).

    Attributes:
        db: The injected database facade.
        sensor_registry: The injected configured sensor registry.
        analytics_config: The injected Analytics Engine configuration.
        model_manager: The injected model persistence layer.
        settings: The injected application settings (training window,
            minimum sample count, resampling frequency, etc.).
    """

    def __init__(
        self,
        db: Optional[DatabaseService] = None,
        sensor_registry: Optional[SensorRegistry] = None,
        analytics_config: Optional[AnalyticsConfig] = None,
        model_manager: Optional[ModelManager] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            db: The database facade. Defaults to the process-wide
                cached :class:`DatabaseService`.
            sensor_registry: The configured sensor registry. Defaults
                to the process-wide cached :class:`SensorRegistry`.
            analytics_config: The Analytics Engine configuration.
                Defaults to the process-wide cached
                :class:`AnalyticsConfig`.
            model_manager: The model persistence layer. Defaults to a
                :class:`ModelManager` rooted at ``settings.ml_model_dir``.
            settings: Application settings. Defaults to the
                process-wide cached :class:`Settings`.
        """
        self.settings = settings or get_settings()
        self.db = db or get_database_service()
        self.sensor_registry = sensor_registry or get_sensor_registry()
        self.analytics_config = analytics_config or get_analytics_config()
        self.model_manager = model_manager or ModelManager(self.settings.ml_model_dir)
        self.dataset_builder = DatasetBuilder(self.db, self.sensor_registry, self.analytics_config)

    def _training_window(self) -> Tuple[datetime, datetime]:
        """Resolve the default ``(start, end)`` training window from settings.

        Returns:
            A ``(start, end)`` tuple spanning
            ``settings.ml_training_window_days`` days up to now.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.settings.ml_training_window_days)
        return start, end

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def prepare_anomaly_dataset(self, device_name: Optional[str] = None) -> pd.DataFrame:
        """Build the engineered multivariate feature frame anomaly detection uses.

        Shared verbatim by :meth:`train_anomaly_detector` (fits on
        every row) and
        :meth:`app.ml.inference.MLInferenceService.detect_anomaly`
        (scores only the last/most-recent row) - one feature space,
        never two.

        Args:
            device_name: Optional device filter.

        Returns:
            An engineered, ``NaN``-free feature frame, oldest row
            first.
        """
        start, end = self._training_window()
        dataset = self.dataset_builder.build(
            DEFAULT_MONITORING_PARAMETERS,
            start,
            end,
            device_name=device_name,
            resample_frequency=self.settings.ml_resample_frequency,
        )
        config = FeatureConfig(roll_windows=[3, 24], lag_counts=1, include_calendar_features=True)
        return build_features(dataset.frame, config)

    def train_anomaly_detector(self, device_name: Optional[str] = None) -> ModelMetadata:
        """Train and persist a new :class:`AnomalyDetector` version.

        Args:
            device_name: Optional device filter for the training data.

        Returns:
            The saved version's :class:`ModelMetadata`.

        Raises:
            InsufficientDataError: If fewer than
                ``settings.ml_min_training_samples`` usable rows are
                available.
        """
        features = self.prepare_anomaly_dataset(device_name)
        if len(features) < self.settings.ml_min_training_samples:
            raise InsufficientDataError(
                f"Only {len(features)} usable row(s) available for anomaly detection training "
                f"(need {self.settings.ml_min_training_samples})."
            )

        detector = AnomalyDetector(
            contamination=self.settings.ml_anomaly_contamination,
            random_state=self.settings.ml_random_state,
        ).fit(features)

        return self.model_manager.save(
            ANOMALY_MODEL_NAME,
            detector,
            algorithm="isolation_forest",
            training_rows=len(features),
            extra={"feature_names": detector.feature_names_, "device_name": device_name},
        )

    # ------------------------------------------------------------------
    # Trend prediction
    # ------------------------------------------------------------------

    def prepare_trend_dataset(
        self, parameter: str, horizon: PredictionHorizon, device_name: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Build the engineered features and shifted target trend prediction uses.

        Shared verbatim by :meth:`train_trend_predictor` (drops the
        trailing rows whose target is unknown, then trains) and
        :meth:`app.ml.inference.MLInferenceService.predict` (uses the
        *last* feature row - the one whose target is, by definition,
        unknown - as the row to predict for).

        Args:
            parameter: The forecast target parameter's key.
            horizon: The forecast horizon.
            device_name: Optional device filter.

        Returns:
            An ``(X, y)`` tuple: ``X`` is the full engineered feature
            frame (every row, oldest first); ``y`` is ``X[parameter]``
            shifted ``HORIZON_STEPS[horizon]`` rows into the future,
            aligned with ``X``'s index (its trailing rows are
            ``NaN`` - by definition, since the future value isn't
            known yet for the most recent rows).

        Raises:
            NotFoundError: If ``parameter`` is unknown.
        """
        start, end = self._training_window()
        parameters = sorted(set(DEFAULT_TREND_PARAMETERS) | {parameter})
        dataset = self.dataset_builder.build(
            parameters, start, end, device_name=device_name, resample_frequency=self.settings.ml_resample_frequency
        )
        config = FeatureConfig(roll_windows=[3, 24], lag_counts=3, include_calendar_features=True)
        features = build_features(dataset.frame, config)

        if parameter not in features.columns:
            raise InsufficientDataError(f"'{parameter}' has no usable historical data in the training window.")

        steps = HORIZON_STEPS[horizon]
        target = features[parameter].shift(-steps).rename(f"{parameter}_target")
        return features, target

    def train_trend_predictor(
        self, parameter: str, horizon: PredictionHorizon, device_name: Optional[str] = None
    ) -> ModelMetadata:
        """Train and persist a new :class:`TrendPredictor` version.

        Args:
            parameter: The forecast target parameter's key.
            horizon: The forecast horizon.
            device_name: Optional device filter for the training data.

        Returns:
            The saved version's :class:`ModelMetadata`.

        Raises:
            InsufficientDataError: If fewer than
                ``settings.ml_min_training_samples`` usable
                (feature, known-target) rows are available.
        """
        features, target = self.prepare_trend_dataset(parameter, horizon, device_name)
        training_frame = features.assign(**{target.name: target}).dropna()
        if len(training_frame) < self.settings.ml_min_training_samples:
            raise InsufficientDataError(
                f"Only {len(training_frame)} usable row(s) available to train the "
                f"'{parameter}' / '{horizon.value}' trend predictor "
                f"(need {self.settings.ml_min_training_samples})."
            )

        X = training_frame.drop(columns=[target.name])
        y = training_frame[target.name]

        predictor = TrendPredictor(
            parameter=parameter,
            horizon=horizon.value,
            algorithm="random_forest",
            random_state=self.settings.ml_random_state,
        ).train(X, y)

        return self.model_manager.save(
            trend_model_name(parameter, horizon),
            predictor,
            algorithm=predictor.algorithm,
            metrics=predictor.metrics_,
            training_rows=len(X),
            extra={"feature_names": predictor.feature_names_, "device_name": device_name},
        )

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def train_all(
        self,
        parameters: Optional[List[str]] = None,
        horizons: Optional[List[PredictionHorizon]] = None,
        device_name: Optional[str] = None,
    ) -> TrainingSummary:
        """Train the anomaly detector and every requested trend predictor.

        Never raises for an individual model's insufficient data -
        each failure is recorded in
        :attr:`TrainingSummary.skipped` and training continues with
        the next model, so one under-populated sensor doesn't block
        every other model from training.

        Args:
            parameters: Trend-prediction target parameters. Defaults
                to :data:`app.ml.utils.DEFAULT_TREND_PARAMETERS`.
            horizons: Forecast horizons to train per parameter.
                Defaults to every :class:`PredictionHorizon`.
            device_name: Optional device filter for every model's
                training data.

        Returns:
            A populated :class:`TrainingSummary`.
        """
        parameters = parameters or DEFAULT_TREND_PARAMETERS
        horizons = horizons or list(PredictionHorizon)
        summary = TrainingSummary()

        try:
            summary.anomaly_model = self.train_anomaly_detector(device_name)
        except InsufficientDataError as exc:
            summary.skipped[ANOMALY_MODEL_NAME] = str(exc)
            logger.warning(f"Skipped training {ANOMALY_MODEL_NAME}: {exc}")

        for parameter in parameters:
            for horizon in horizons:
                name = trend_model_name(parameter, horizon)
                try:
                    summary.trend_models[name] = self.train_trend_predictor(parameter, horizon, device_name)
                except InsufficientDataError as exc:
                    summary.skipped[name] = str(exc)
                    logger.warning(f"Skipped training {name}: {exc}")

        logger.info(
            f"Training complete: trained={len(summary.trend_models) + (1 if summary.anomaly_model else 0)} "
            f"skipped={len(summary.skipped)}"
        )
        return summary


__all__ = ["TrainingPipeline", "TrainingSummary", "ANOMALY_MODEL_NAME", "trend_model_name"]


if __name__ == "__main__":
    pipeline = TrainingPipeline()
    result = pipeline.train_all()
    print(f"Anomaly model: {result.anomaly_model}")
    print(f"Trend models trained: {len(result.trend_models)}")
    print(f"Skipped: {result.skipped}")
