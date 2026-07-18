"""Pydantic response models for the AI Decision Support Engine.

Used directly as the REST API's ``response_model``\\ s (see
``app/api/routers/ml.py``) and as
:class:`app.ml.inference.MLInferenceService`'s return types - kept in
this package for the same reason as
``app.historical.schemas``: these describe this module's own data
contracts, independent of transport.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.ml.utils import HealthCategory, MLStatus, PredictionHorizon

__all__ = [
    "MLStatus",
    "PredictionHorizon",
    "HealthCategory",
    "ModelInfo",
    "TrendPredictionData",
    "AnomalyData",
    "PollutionProbabilityData",
    "RiverHealthForecastData",
]


class ModelInfo(BaseModel):
    """Model metadata included in every ML API response.

    Attributes:
        model_name: The logical model name (see
            :class:`app.ml.model_manager.ModelMetadata`).
        version: The specific version used to serve this response.
        algorithm: A short label for the underlying algorithm.
        trained_at: When the serving model version finished training.
        freshly_trained: ``True`` if this request triggered training
            on demand (no cached model existed yet); ``False`` if a
            previously saved model was reused.
    """

    model_name: str
    version: str
    algorithm: str
    trained_at: datetime
    freshly_trained: bool = False


class TrendPredictionData(BaseModel):
    """Payload for ``GET /ml/predictions``.

    Attributes:
        status: The outcome of this inference call.
        parameter: The forecast parameter's key.
        display_name: Human friendly parameter name.
        unit: Unit of measurement, if known.
        horizon: The forecast horizon.
        device_name: The device filter applied, or ``None``.
        timestamp: When this forecast was computed (UTC).
        current_value: The most recent observed value.
        predicted_value: The forecast value.
        confidence_interval_lower: Lower bound of an approximate 95%
            confidence interval.
        confidence_interval_upper: Upper bound of an approximate 95%
            confidence interval.
        model_confidence: A ``0.0``-``1.0`` model confidence score.
        model: Serving model metadata, ``None`` if ``status`` is not
            ``ok``.
    """

    status: MLStatus
    parameter: str
    display_name: str
    unit: Optional[str] = None
    horizon: PredictionHorizon
    device_name: Optional[str] = None
    timestamp: datetime
    current_value: Optional[float] = None
    predicted_value: Optional[float] = None
    confidence_interval_lower: Optional[float] = None
    confidence_interval_upper: Optional[float] = None
    model_confidence: Optional[float] = None
    model: Optional[ModelInfo] = None


class AnomalyData(BaseModel):
    """Payload for ``GET /ml/anomalies``.

    Attributes:
        status: The outcome of this inference call.
        device_name: The device filter applied, or ``None``.
        timestamp: When this snapshot was scored (UTC).
        anomaly_score: A ``0.0``-``1.0`` score, higher = more
            anomalous.
        is_anomaly: Whether the current snapshot is classified as
            anomalous.
        confidence: A ``0.0``-``1.0`` confidence in the label.
        contributing_parameters: Parameters that deviate most from
            what the model considers typical, most-deviating first.
        evaluated_parameters: Every parameter included in the
            multivariate snapshot the model scored.
        model: Serving model metadata, ``None`` if ``status`` is not
            ``ok``.
    """

    status: MLStatus
    device_name: Optional[str] = None
    timestamp: datetime
    anomaly_score: Optional[float] = None
    is_anomaly: Optional[bool] = None
    confidence: Optional[float] = None
    contributing_parameters: List[str] = Field(default_factory=list)
    evaluated_parameters: List[str] = Field(default_factory=list)
    model: Optional[ModelInfo] = None


class PollutionProbabilityData(BaseModel):
    """Payload for ``GET /ml/pollution``.

    Attributes:
        status: The outcome of this inference call.
        device_name: The device filter applied, or ``None``.
        timestamp: When this classification was computed (UTC).
        probabilities: Source key -> probability, summing to ``1.0``.
        most_likely_source: The highest-probability source.
        notes: Short, human-readable reasons the top rules fired.
        model: Serving model metadata (``algorithm="rule_assisted"``),
            ``None`` if ``status`` is not ``ok``.
    """

    status: MLStatus
    device_name: Optional[str] = None
    timestamp: datetime
    probabilities: Dict[str, float] = Field(default_factory=dict)
    most_likely_source: Optional[str] = None
    notes: List[str] = Field(default_factory=list)
    model: Optional[ModelInfo] = None


class RiverHealthForecastData(BaseModel):
    """Payload for ``GET /ml/river-health``.

    Attributes:
        status: The outcome of this inference call.
        device_name: The device filter applied, or ``None``.
        timestamp: When this forecast was computed (UTC).
        horizon: The forecast horizon.
        current_score: The composite River Health Score right now
            (``0``-``100``).
        predicted_score: The forecast composite score at ``horizon``.
        health_category: The qualitative category of
            ``predicted_score``.
        confidence: A ``0.0``-``1.0`` confidence in the forecast.
        model: Serving model metadata, ``None`` if ``status`` is not
            ``ok``.
    """

    status: MLStatus
    device_name: Optional[str] = None
    timestamp: datetime
    horizon: PredictionHorizon
    current_score: Optional[float] = None
    predicted_score: Optional[float] = None
    health_category: Optional[HealthCategory] = None
    confidence: Optional[float] = None
    model: Optional[ModelInfo] = None
