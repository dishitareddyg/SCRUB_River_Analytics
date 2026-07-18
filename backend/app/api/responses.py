"""Typed response envelopes and helpers for the REST API layer.

Every endpoint responds using the existing, standardized envelope
models from :mod:`app.utils.response` (``SuccessResponse`` /
``ErrorResponse``), established by the backend foundation module -
this module does not define a competing response shape, only:

    1. Endpoint-specific type aliases (e.g. ``LiveSensorsResponse``)
       so each router can declare a precise ``response_model`` for
       OpenAPI documentation.
    2. A tiny :func:`success` helper to reduce boilerplate when
       building a ``SuccessResponse`` in a route handler.

Every :class:`~app.utils.response.SuccessResponse` /
:class:`~app.utils.response.ErrorResponse` already carries a
``success``/``error`` status indicator, a human readable ``message``,
and a ``meta.timestamp`` - satisfying this module's "every response
contains status, message, timestamp" requirement without introducing
a second, parallel envelope convention.

Error responses (404/400/422/500) are produced automatically by the
global exception handlers registered in ``app/main.py`` whenever a
route raises an :class:`~app.utils.exceptions.ApplicationError`
subclass (see :mod:`app.utils.exceptions` for
:class:`~app.utils.exceptions.NotFoundError`,
:class:`~app.utils.exceptions.BadRequestError`, and
:class:`~app.utils.exceptions.ValidationError`) or when FastAPI's own
request validation fails - routers never need to build an
``ErrorResponse`` by hand.
"""

from __future__ import annotations

from typing import Optional, TypeVar

from app.api.schemas.analytics import AnalyticsHistoryData, AnalyticsLatestData
from app.api.schemas.history import SensorHistoryData
from app.api.schemas.sensor import LiveSensorsData
from app.api.schemas.system import SystemHealthData, SystemInfoData
from app.historical.schemas import ComparisonData, SeasonalData, StatisticsData, TrendData
from app.ml.schemas import AnomalyData, PollutionProbabilityData, RiverHealthForecastData, TrendPredictionData
from app.utils.response import SuccessResponse

DataT = TypeVar("DataT")

# ---------------------------------------------------------------------------
# Endpoint-specific response type aliases (used as `response_model=...`).
# ---------------------------------------------------------------------------
LiveSensorsResponse = SuccessResponse[LiveSensorsData]
AnalyticsLatestResponse = SuccessResponse[AnalyticsLatestData]
AnalyticsHistoryResponse = SuccessResponse[AnalyticsHistoryData]
SensorHistoryResponse = SuccessResponse[SensorHistoryData]
SystemHealthApiResponse = SuccessResponse[SystemHealthData]
SystemInfoApiResponse = SuccessResponse[SystemInfoData]
HistoricalStatisticsResponse = SuccessResponse[StatisticsData]
HistoricalTrendResponse = SuccessResponse[TrendData]
HistoricalSeasonalResponse = SuccessResponse[SeasonalData]
HistoricalComparisonResponse = SuccessResponse[ComparisonData]
MLPredictionResponse = SuccessResponse[TrendPredictionData]
MLAnomalyResponse = SuccessResponse[AnomalyData]
MLPollutionResponse = SuccessResponse[PollutionProbabilityData]
MLRiverHealthResponse = SuccessResponse[RiverHealthForecastData]


def success(
    data: DataT, message: str = "Request completed successfully."
) -> SuccessResponse[DataT]:
    """Build a standard :class:`SuccessResponse` envelope.

    Args:
        data: The endpoint-specific payload.
        message: A short, human readable summary of the result.

    Returns:
        A populated :class:`~app.utils.response.SuccessResponse`.
    """
    return SuccessResponse(data=data, message=message)
