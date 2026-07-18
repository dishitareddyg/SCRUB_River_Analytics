"""On-demand inference façade for the AI Decision Support Engine.

:class:`MLInferenceService` is the single entry point the REST API
depends on (``app/api/routers/ml.py``), providing the four reusable
functions this module's requirements call for:
:meth:`~MLInferenceService.predict`,
:meth:`~MLInferenceService.detect_anomaly`,
:meth:`~MLInferenceService.classify_pollution`, and
:meth:`~MLInferenceService.forecast_river_health`.

**Predictions are computed on demand.** Rather than requiring a
separate training step before the API can respond (impractical for a
module meant to "just work" locally), each method first tries
:class:`~app.ml.model_manager.ModelManager` for a previously saved
model; if none exists yet, it trains one on the spot via
:class:`~app.ml.trainer.TrainingPipeline` (small, fast estimators by
design - see that module), serves the prediction, and leaves the
newly trained model saved for next time. ``python -m app.ml.trainer``
remains available to pre-train every model up front (e.g. in a
deployment's startup script) so the *first* API request doesn't pay
the training cost.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.config.settings import Settings, get_settings
from app.database.service import DatabaseService, get_database_service
from app.historical.service import HistoricalAnalyticsService
from app.historical.utils import HistoryWindow
from app.ml.anomaly_detector import AnomalyDetector
from app.ml.model_manager import ModelManager, ModelMetadata
from app.ml.pollution_classifier import FeatureSnapshot, PollutionClassifier
from app.ml.river_health_predictor import DEFAULT_WEIGHTS, RiverHealthPredictor
from app.ml.schemas import (
    AnomalyData,
    ModelInfo,
    PollutionProbabilityData,
    RiverHealthForecastData,
    TrendPredictionData,
)
from app.ml.trainer import ANOMALY_MODEL_NAME, TrainingPipeline, trend_model_name
from app.ml.trend_predictor import TrendPredictor
from app.ml.utils import (
    DEFAULT_TREND_PARAMETERS,
    InsufficientDataError,
    MLStatus,
    PredictionHorizon,
    horizon_to_seconds,
)
from app.serial.sensor_registry import SensorRegistry, get_sensor_registry
from app.utils.exceptions import BadRequestError, NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Sensor parameters read for the pollution classifier's current-value
#: snapshot (a subset that has a direct sensor reading, unlike
#: derived analytics parameters).
_POLLUTION_SNAPSHOT_PARAMETERS = [
    "dissolved_oxygen",
    "conductivity",
    "turbidity",
    "ph_level",
    "orp",
    "water_temperature",
    "rainfall",
]

#: Parameters whose recent trend percentage feeds the pollution
#: classifier's rules (see app.ml.pollution_classifier).
_POLLUTION_TREND_PARAMETERS = ["dissolved_oxygen", "conductivity", "turbidity", "rainfall"]


class MLInferenceService:
    """Reusable, on-demand façade over every AI Decision Support Engine model.

    Every dependency is injected through the constructor (Dependency
    Injection coding standard, matching every other service in this
    codebase - see
    :class:`app.historical.service.HistoricalAnalyticsService` for the
    identical pattern).

    Attributes:
        db: The injected database facade.
        sensor_registry: The injected configured sensor registry.
        analytics_config: The injected Analytics Engine configuration.
        model_manager: The injected model persistence layer.
        settings: The injected application settings.
        historical_service: The injected
            :class:`~app.historical.service.HistoricalAnalyticsService`,
            reused here for trend deltas rather than recomputing them.
        pipeline: The injected :class:`~app.ml.trainer.TrainingPipeline`,
            reused both to train on demand and to build the current
            feature snapshot a cached model predicts from.
    """

    def __init__(
        self,
        db: Optional[DatabaseService] = None,
        sensor_registry: Optional[SensorRegistry] = None,
        analytics_config: Optional[AnalyticsConfig] = None,
        model_manager: Optional[ModelManager] = None,
        settings: Optional[Settings] = None,
        historical_service: Optional[HistoricalAnalyticsService] = None,
        pipeline: Optional[TrainingPipeline] = None,
    ) -> None:
        """Initialize the service.

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
            historical_service: A
                :class:`~app.historical.service.HistoricalAnalyticsService`.
                Built from the same collaborators if omitted.
            pipeline: A :class:`~app.ml.trainer.TrainingPipeline`.
                Built from the same collaborators if omitted.
        """
        self.settings = settings or get_settings()
        self.db = db or get_database_service()
        self.sensor_registry = sensor_registry or get_sensor_registry()
        self.analytics_config = analytics_config or get_analytics_config()
        self.model_manager = model_manager or ModelManager(self.settings.ml_model_dir)
        self.historical_service = historical_service or HistoricalAnalyticsService(
            self.db, self.sensor_registry, self.analytics_config
        )
        self.pipeline = pipeline or TrainingPipeline(
            self.db, self.sensor_registry, self.analytics_config, self.model_manager, self.settings
        )

    def _model_info(self, metadata: ModelMetadata, freshly_trained: bool) -> ModelInfo:
        """Build the API-facing :class:`~app.ml.schemas.ModelInfo` block.

        Args:
            metadata: The serving model version's metadata.
            freshly_trained: Whether this request triggered training.

        Returns:
            A populated :class:`~app.ml.schemas.ModelInfo`.
        """
        return ModelInfo(
            model_name=metadata.model_name,
            version=metadata.version,
            algorithm=metadata.algorithm,
            trained_at=datetime.fromisoformat(metadata.trained_at),
            freshly_trained=freshly_trained,
        )

    # ------------------------------------------------------------------
    # Trend Prediction
    # ------------------------------------------------------------------

    def predict(
        self, parameter: str, horizon: PredictionHorizon, device_name: Optional[str] = None
    ) -> TrendPredictionData:
        """Forecast ``parameter``'s value at ``horizon``.

        Args:
            parameter: One of :data:`app.ml.utils.DEFAULT_TREND_PARAMETERS`.
            horizon: The forecast horizon.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.ml.schemas.TrendPredictionData`.

        Raises:
            BadRequestError: If ``parameter`` isn't a supported trend
                target.
        """
        if parameter not in DEFAULT_TREND_PARAMETERS:
            raise BadRequestError(
                f"Trend prediction supports {DEFAULT_TREND_PARAMETERS}, got '{parameter}'."
            )

        timestamp = datetime.now(timezone.utc)
        model_name = trend_model_name(parameter, horizon)
        display_name, unit = self._parameter_meta(parameter)

        try:
            predictor, metadata, freshly_trained = self._load_or_train_trend_predictor(
                parameter, horizon, device_name, model_name
            )
        except InsufficientDataError as exc:
            logger.warning(f"predict() insufficient data: {exc}")
            return TrendPredictionData(
                status=MLStatus.INSUFFICIENT_DATA,
                parameter=parameter,
                display_name=display_name,
                unit=unit,
                horizon=horizon,
                device_name=device_name,
                timestamp=timestamp,
            )

        features, _ = self.pipeline.prepare_trend_dataset(parameter, horizon, device_name)
        prediction = predictor.predict(features)
        current_value = float(features[parameter].iloc[-1])

        return TrendPredictionData(
            status=MLStatus.OK,
            parameter=parameter,
            display_name=display_name,
            unit=unit,
            horizon=horizon,
            device_name=device_name,
            timestamp=timestamp,
            current_value=round(current_value, 4),
            predicted_value=prediction.predicted_value,
            confidence_interval_lower=prediction.confidence_interval_lower,
            confidence_interval_upper=prediction.confidence_interval_upper,
            model_confidence=prediction.model_confidence,
            model=self._model_info(metadata, freshly_trained),
        )

    def _load_or_train_trend_predictor(
        self, parameter: str, horizon: PredictionHorizon, device_name: Optional[str], model_name: str
    ) -> tuple[TrendPredictor, ModelMetadata, bool]:
        """Load a cached trend predictor, training one on demand if none exists.

        Args:
            parameter: The forecast target parameter's key.
            horizon: The forecast horizon.
            device_name: Optional device filter.
            model_name: The logical model name to load/save.

        Returns:
            A ``(predictor, metadata, freshly_trained)`` tuple.

        Raises:
            InsufficientDataError: If no cached model exists and too
                little data is available to train one.
        """
        try:
            predictor, metadata = self.model_manager.load(model_name)
            return predictor, metadata, False
        except NotFoundError:
            metadata = self.pipeline.train_trend_predictor(parameter, horizon, device_name)
            predictor, _ = self.model_manager.load(model_name, metadata.version)
            return predictor, metadata, True

    def _parameter_meta(self, parameter: str) -> tuple[str, Optional[str]]:
        """Resolve a parameter's display name and unit from the sensor registry.

        Args:
            parameter: A sensor's canonical key.

        Returns:
            A ``(display_name, unit)`` tuple, falling back to
            ``(parameter, None)`` if unrecognized.
        """
        sensor = self.sensor_registry.get(parameter)
        if sensor is None:
            return parameter, None
        return sensor.display_name, sensor.unit

    # ------------------------------------------------------------------
    # Anomaly Detection
    # ------------------------------------------------------------------

    def detect_anomaly(self, device_name: Optional[str] = None) -> AnomalyData:
        """Score the current multi-sensor snapshot for anomalies.

        Args:
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.ml.schemas.AnomalyData`.
        """
        timestamp = datetime.now(timezone.utc)

        try:
            detector, metadata, freshly_trained = self._load_or_train_anomaly_detector(device_name)
        except InsufficientDataError as exc:
            logger.warning(f"detect_anomaly() insufficient data: {exc}")
            return AnomalyData(status=MLStatus.INSUFFICIENT_DATA, device_name=device_name, timestamp=timestamp)

        features = self.pipeline.prepare_anomaly_dataset(device_name)
        latest_row = features.iloc[-1]
        prediction = detector.predict_row(latest_row)

        return AnomalyData(
            status=MLStatus.OK,
            device_name=device_name,
            timestamp=timestamp,
            anomaly_score=prediction.anomaly_score,
            is_anomaly=prediction.is_anomaly,
            confidence=prediction.confidence,
            contributing_parameters=prediction.contributing_parameters,
            evaluated_parameters=detector.feature_names_,
            model=self._model_info(metadata, freshly_trained),
        )

    def _load_or_train_anomaly_detector(
        self, device_name: Optional[str]
    ) -> tuple[AnomalyDetector, ModelMetadata, bool]:
        """Load a cached anomaly detector, training one on demand if none exists.

        Args:
            device_name: Optional device filter.

        Returns:
            A ``(detector, metadata, freshly_trained)`` tuple.

        Raises:
            InsufficientDataError: If no cached model exists and too
                little data is available to train one.
        """
        try:
            detector, metadata = self.model_manager.load(ANOMALY_MODEL_NAME)
            return detector, metadata, False
        except NotFoundError:
            metadata = self.pipeline.train_anomaly_detector(device_name)
            detector, _ = self.model_manager.load(ANOMALY_MODEL_NAME, metadata.version)
            return detector, metadata, True

    # ------------------------------------------------------------------
    # Pollution Source Probability
    # ------------------------------------------------------------------

    def classify_pollution(self, device_name: Optional[str] = None) -> PollutionProbabilityData:
        """Estimate a probability distribution over candidate pollution sources.

        Rule-assisted, not a trained model - see
        :mod:`app.ml.pollution_classifier` for why, and always returns
        ``status=OK`` with a (possibly ``UNKNOWN``-dominated)
        distribution as long as at least one relevant sensor has ever
        reported a value; only reports ``INSUFFICIENT_DATA`` if none
        has.

        Args:
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.ml.schemas.PollutionProbabilityData`.
        """
        timestamp = datetime.now(timezone.utc)
        snapshot, any_data = self._build_pollution_snapshot(device_name)

        if not any_data:
            return PollutionProbabilityData(
                status=MLStatus.INSUFFICIENT_DATA, device_name=device_name, timestamp=timestamp
            )

        result = PollutionClassifier().classify(snapshot)
        return PollutionProbabilityData(
            status=MLStatus.OK,
            device_name=device_name,
            timestamp=timestamp,
            probabilities=result.probabilities,
            most_likely_source=result.most_likely_source,
            notes=result.notes,
            model=ModelInfo(
                model_name="pollution_classifier",
                version="rule-assisted",
                algorithm="rule_assisted",
                trained_at=timestamp,
                freshly_trained=False,
            ),
        )

    def _build_pollution_snapshot(self, device_name: Optional[str]) -> tuple[FeatureSnapshot, bool]:
        """Assemble the current-value + recent-trend snapshot pollution rules read.

        Args:
            device_name: Optional device filter.

        Returns:
            A ``(snapshot, any_data_found)`` tuple.
        """
        values: Dict[str, Optional[float]] = {}
        any_data = False
        for parameter in _POLLUTION_SNAPSHOT_PARAMETERS:
            latest = self.db.get_latest_readings(device_name=device_name, sensor_key=parameter, limit=1)
            if latest and latest[0].value is not None:
                values[parameter] = latest[0].value
                any_data = True
            else:
                values[parameter] = None

        trends: Dict[str, Optional[float]] = {}
        for parameter in _POLLUTION_TREND_PARAMETERS:
            try:
                trend = self.historical_service.get_trends(
                    parameter, window=HistoryWindow.DAY, device_name=device_name
                )
                trends[parameter] = trend.trend_percentage
                any_data = any_data or trend.sample_count > 0
            except NotFoundError:
                trends[parameter] = None

        snapshot = FeatureSnapshot(
            dissolved_oxygen=values.get("dissolved_oxygen"),
            dissolved_oxygen_trend_percent=trends.get("dissolved_oxygen"),
            conductivity=values.get("conductivity"),
            conductivity_trend_percent=trends.get("conductivity"),
            turbidity=values.get("turbidity"),
            turbidity_trend_percent=trends.get("turbidity"),
            ph_level=values.get("ph_level"),
            orp=values.get("orp"),
            water_temperature=values.get("water_temperature"),
            rainfall=values.get("rainfall"),
            rainfall_trend_percent=trends.get("rainfall"),
        )
        return snapshot, any_data

    # ------------------------------------------------------------------
    # River Health Forecast
    # ------------------------------------------------------------------

    def forecast_river_health(
        self, horizon: PredictionHorizon, device_name: Optional[str] = None
    ) -> RiverHealthForecastData:
        """Forecast the composite River Health Score at ``horizon``.

        Args:
            horizon: The forecast horizon.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.ml.schemas.RiverHealthForecastData`.
        """
        timestamp = datetime.now(timezone.utc)
        predictor = RiverHealthPredictor()

        start = timestamp - timedelta(days=self.settings.ml_training_window_days)
        dataset = self.pipeline.dataset_builder.build(
            list(DEFAULT_WEIGHTS.keys()),
            start,
            timestamp,
            device_name=device_name,
            resample_frequency=self.settings.ml_resample_frequency,
        )

        if dataset.frame.empty:
            return RiverHealthForecastData(
                status=MLStatus.INSUFFICIENT_DATA, device_name=device_name, timestamp=timestamp, horizon=horizon
            )

        scores = dataset.frame.apply(lambda row: predictor.compute_score(row.to_dict()), axis=1).dropna()
        if len(scores) < 2:
            return RiverHealthForecastData(
                status=MLStatus.INSUFFICIENT_DATA, device_name=device_name, timestamp=timestamp, horizon=horizon
            )

        first_timestamp = scores.index[0]
        score_history = [((idx - first_timestamp).total_seconds(), value) for idx, value in scores.items()]
        horizon_seconds = horizon_to_seconds(horizon, self.settings.ml_resample_frequency)

        forecast = predictor.forecast(score_history, horizon_seconds)
        if forecast is None:
            return RiverHealthForecastData(
                status=MLStatus.INSUFFICIENT_DATA, device_name=device_name, timestamp=timestamp, horizon=horizon
            )

        return RiverHealthForecastData(
            status=MLStatus.OK,
            device_name=device_name,
            timestamp=timestamp,
            horizon=horizon,
            current_score=forecast.current_score,
            predicted_score=forecast.predicted_score,
            health_category=forecast.category,
            confidence=forecast.confidence,
            model=ModelInfo(
                model_name="river_health_forecast",
                version="on-demand-linear-trend",
                algorithm="ols_linear_trend",
                trained_at=timestamp,
                freshly_trained=True,
            ),
        )


__all__ = ["MLInferenceService"]
