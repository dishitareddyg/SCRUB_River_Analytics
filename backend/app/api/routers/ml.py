"""AI Decision Support Engine endpoints (``/ml``).

Four endpoints, one per capability this module provides, each backed
by :class:`app.ml.inference.MLInferenceService` and returning the same
standardized response envelope as every other router:

    - ``GET /ml/predictions?parameter=&horizon=&device_name=`` -
      short-horizon trend forecast for a supported parameter.
    - ``GET /ml/anomalies?device_name=`` - current multi-sensor
      anomaly score/label.
    - ``GET /ml/pollution?device_name=`` - pollution source
      probability distribution.
    - ``GET /ml/river-health?horizon=&device_name=`` - composite River
      Health Score forecast.

Every response includes a timestamp, confidence score(s), and model
metadata (see :class:`app.ml.schemas.ModelInfo`), and reports
``status="insufficient_data"`` rather than fabricating a result when
too little historical data exists yet.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_ml_inference_service_dependency
from app.api.responses import (
    MLAnomalyResponse,
    MLPollutionResponse,
    MLPredictionResponse,
    MLRiverHealthResponse,
    success,
)
from app.ml.inference import MLInferenceService
from app.ml.schemas import AnomalyData, PollutionProbabilityData, RiverHealthForecastData, TrendPredictionData
from app.ml.utils import DEFAULT_TREND_PARAMETERS, MLStatus, PredictionHorizon

router = APIRouter(tags=["AI Decision Support"])


@router.get(
    "/predictions",
    response_model=MLPredictionResponse,
    summary="Trend prediction",
    description=(
        "Forecasts a supported parameter's value at a given horizon using a Random "
        f"Forest / XGBoost regressor. Supported parameters: {DEFAULT_TREND_PARAMETERS}."
    ),
)
def get_predictions(
    parameter: str = Query(..., description="Forecast target parameter key.", examples=["dissolved_oxygen"]),
    horizon: PredictionHorizon = Query(PredictionHorizon.NEXT_HOUR, description="Forecast horizon."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: MLInferenceService = Depends(get_ml_inference_service_dependency),
) -> MLPredictionResponse:
    """Forecast one parameter's value at one horizon.

    Args:
        parameter: Forecast target parameter key.
        horizon: The forecast horizon.
        device_name: Optional device filter.
        service: Injected :class:`MLInferenceService`.

    Returns:
        A :class:`~app.api.responses.MLPredictionResponse`.

    Raises:
        BadRequestError: If ``parameter`` is not a supported trend
            target.
    """
    data: TrendPredictionData = service.predict(parameter, horizon, device_name=device_name)
    message = (
        f"Predicted {data.parameter} ({horizon.value}): {data.predicted_value}"
        if data.status == MLStatus.OK
        else "Not enough historical data yet to forecast this parameter."
    )
    return success(data, message)


@router.get(
    "/anomalies",
    response_model=MLAnomalyResponse,
    summary="Anomaly detection",
    description=(
        "Scores the current multi-sensor snapshot for anomalies via an Isolation "
        "Forest trained on recent historical data."
    ),
)
def get_anomalies(
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: MLInferenceService = Depends(get_ml_inference_service_dependency),
) -> MLAnomalyResponse:
    """Score the current multi-sensor snapshot for anomalies.

    Args:
        device_name: Optional device filter.
        service: Injected :class:`MLInferenceService`.

    Returns:
        A :class:`~app.api.responses.MLAnomalyResponse`.
    """
    data: AnomalyData = service.detect_anomaly(device_name=device_name)
    message = (
        ("Anomaly detected." if data.is_anomaly else "No anomaly detected.")
        if data.status == MLStatus.OK
        else "Not enough historical data yet to run anomaly detection."
    )
    return success(data, message)


@router.get(
    "/pollution",
    response_model=MLPollutionResponse,
    summary="Pollution source probability",
    description=(
        "Estimates a probability distribution over candidate pollution sources "
        "(domestic sewage, agricultural runoff, industrial effluent, stormwater, "
        "natural variation, unknown) from current readings and recent trends. "
        "Rule-assisted, not a confident determination."
    ),
)
def get_pollution(
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: MLInferenceService = Depends(get_ml_inference_service_dependency),
) -> MLPollutionResponse:
    """Estimate a probability distribution over candidate pollution sources.

    Args:
        device_name: Optional device filter.
        service: Injected :class:`MLInferenceService`.

    Returns:
        A :class:`~app.api.responses.MLPollutionResponse`.
    """
    data: PollutionProbabilityData = service.classify_pollution(device_name=device_name)
    message = (
        f"Most likely source: {data.most_likely_source}"
        if data.status == MLStatus.OK
        else "Not enough sensor data yet to estimate a pollution source."
    )
    return success(data, message)


@router.get(
    "/river-health",
    response_model=MLRiverHealthResponse,
    summary="River Health Forecast",
    description=(
        "Forecasts the composite River Health Score at a given horizon from current "
        "conditions and their recent trend."
    ),
)
def get_river_health(
    horizon: PredictionHorizon = Query(PredictionHorizon.NEXT_DAY, description="Forecast horizon."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: MLInferenceService = Depends(get_ml_inference_service_dependency),
) -> MLRiverHealthResponse:
    """Forecast the composite River Health Score at one horizon.

    Args:
        horizon: The forecast horizon.
        device_name: Optional device filter.
        service: Injected :class:`MLInferenceService`.

    Returns:
        A :class:`~app.api.responses.MLRiverHealthResponse`.
    """
    data: RiverHealthForecastData = service.forecast_river_health(horizon, device_name=device_name)
    message = (
        f"Predicted score ({horizon.value}): {data.predicted_score} ({data.health_category.value})"
        if data.status == MLStatus.OK
        else "Not enough historical data yet to forecast river health."
    )
    return success(data, message)
