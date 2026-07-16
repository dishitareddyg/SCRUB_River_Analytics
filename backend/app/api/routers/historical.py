"""Historical Analytics & Trend Engine endpoints (``/history``).

Three endpoints, each accepting either a convenience ``window`` (e.g.
``week``) or an explicit custom ``start``/``end`` range (not both):

    - ``GET /history/statistics/{parameter}`` - summary statistics
      (min/max/mean/median/std-dev/count/latest).
    - ``GET /history/trends/{parameter}`` - trend direction,
      percentage change, rate of change, and trend confidence.
    - ``GET /history/seasonal/{parameter}`` - grouped summaries by
      hour/day/week/month/season/year.

Plus one comparison endpoint (``GET /history/compare``) backing the
dashboard's Comparison Selector.

``{parameter}`` may be either a raw sensor's canonical key (e.g.
``"dissolved_oxygen"``) or a registered analytics parameter key (e.g.
``"tds"``) - see :func:`app.historical.utils.fetch_parameter_series`
for how each is resolved, and this module's sibling
``app/api/routers/history.py`` for the documented anchor-sensor
approximation used for analytics parameters' historical points.

All computation is delegated to
:class:`app.historical.service.HistoricalAnalyticsService` - this
router only translates HTTP query parameters into a service call and
shapes the result into the standard response envelope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies import get_historical_service_dependency
from app.api.responses import (
    HistoricalComparisonResponse,
    HistoricalSeasonalResponse,
    HistoricalStatisticsResponse,
    HistoricalTrendResponse,
    success,
)
from app.historical.aggregation import AggregationInterval
from app.historical.schemas import ComparisonData, SeasonalData, StatisticsData, TrendData
from app.historical.seasonal import SeasonalGroupBy
from app.historical.service import HistoricalAnalyticsService
from app.historical.utils import HistoryWindow
from app.utils.exceptions import BadRequestError

router = APIRouter(tags=["Historical Analytics"])

_WINDOW_DESCRIPTION = (
    "Convenience time-window shortcut. Mutually exclusive with "
    "'start'/'end'; defaults to the last 24 hours if none of "
    "'window'/'start'/'end' are given."
)


@router.get(
    "/statistics/{parameter}",
    response_model=HistoricalStatisticsResponse,
    summary="Historical statistical summary",
    description=(
        "Returns min/max/average/median/standard-deviation/variance/"
        "first/last/percent-change/count for a sensor or derived "
        "analytics parameter over a time window."
    ),
)
def get_statistics(
    parameter: str = Path(..., description="Sensor key or analytics parameter key.", examples=["dissolved_oxygen"]),
    window: Optional[HistoryWindow] = Query(None, description=_WINDOW_DESCRIPTION),
    start: Optional[datetime] = Query(None, description="Inclusive custom range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive custom range end (ISO 8601)."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: HistoricalAnalyticsService = Depends(get_historical_service_dependency),
) -> HistoricalStatisticsResponse:
    """Compute statistical summaries for one parameter over a time window.

    Args:
        parameter: A sensor's canonical key, or an analytics
            parameter key.
        window: A convenience time-window shortcut.
        start: Inclusive custom range start.
        end: Inclusive custom range end.
        device_name: Optional device filter.
        service: Injected :class:`HistoricalAnalyticsService`.

    Returns:
        A :class:`~app.api.responses.HistoricalStatisticsResponse`.

    Raises:
        NotFoundError: If ``parameter`` is unknown.
        BadRequestError: If the time-range query parameters conflict.
    """
    data: StatisticsData = service.get_statistics(
        parameter, window=window, start=start, end=end, device_name=device_name
    )
    message = (
        f"Computed statistics from {data.sample_count} sample(s)."
        if data.sample_count
        else "No data found for the requested range."
    )
    return success(data, message)


@router.get(
    "/trends/{parameter}",
    response_model=HistoricalTrendResponse,
    summary="Historical trend analysis",
    description=(
        "Returns a qualitative trend direction, percent change, rate "
        "of change, and a fit-confidence score for a sensor or "
        "derived analytics parameter over a time window, computed via "
        "ordinary least-squares linear regression (no Machine "
        "Learning)."
    ),
)
def get_trends(
    parameter: str = Path(..., description="Sensor key or analytics parameter key.", examples=["dissolved_oxygen"]),
    window: Optional[HistoryWindow] = Query(None, description=_WINDOW_DESCRIPTION),
    start: Optional[datetime] = Query(None, description="Inclusive custom range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive custom range end (ISO 8601)."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: HistoricalAnalyticsService = Depends(get_historical_service_dependency),
) -> HistoricalTrendResponse:
    """Classify the trend of one parameter over a time window.

    Args:
        parameter: A sensor's canonical key, or an analytics
            parameter key.
        window: A convenience time-window shortcut.
        start: Inclusive custom range start.
        end: Inclusive custom range end.
        device_name: Optional device filter.
        service: Injected :class:`HistoricalAnalyticsService`.

    Returns:
        A :class:`~app.api.responses.HistoricalTrendResponse`.

    Raises:
        NotFoundError: If ``parameter`` is unknown.
        BadRequestError: If the time-range query parameters conflict.
    """
    data: TrendData = service.get_trends(
        parameter, window=window, start=start, end=end, device_name=device_name
    )
    message = f"Trend: {data.direction.value} ({data.sample_count} sample(s))."
    return success(data, message)


@router.get(
    "/seasonal/{parameter}",
    response_model=HistoricalSeasonalResponse,
    summary="Seasonal grouped summaries",
    description=(
        "Groups a sensor or derived analytics parameter's history by "
        "a calendar dimension (hour of day, day of week, ISO week, "
        "month, meteorological season, or year) and returns summary "
        "statistics per group."
    ),
)
def get_seasonal(
    parameter: str = Path(..., description="Sensor key or analytics parameter key.", examples=["dissolved_oxygen"]),
    group_by: SeasonalGroupBy = Query(SeasonalGroupBy.MONTH, description="Calendar dimension to group by."),
    window: Optional[HistoryWindow] = Query(None, description=_WINDOW_DESCRIPTION),
    start: Optional[datetime] = Query(None, description="Inclusive custom range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive custom range end (ISO 8601)."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: HistoricalAnalyticsService = Depends(get_historical_service_dependency),
) -> HistoricalSeasonalResponse:
    """Group one parameter's history by a calendar dimension.

    Args:
        parameter: A sensor's canonical key, or an analytics
            parameter key.
        group_by: The calendar dimension to group by.
        window: A convenience time-window shortcut.
        start: Inclusive custom range start.
        end: Inclusive custom range end.
        device_name: Optional device filter.
        service: Injected :class:`HistoricalAnalyticsService`.

    Returns:
        A :class:`~app.api.responses.HistoricalSeasonalResponse`.

    Raises:
        NotFoundError: If ``parameter`` is unknown.
        BadRequestError: If the time-range query parameters conflict.
    """
    data: SeasonalData = service.get_seasonal(
        parameter, group_by, window=window, start=start, end=end, device_name=device_name
    )
    message = f"Grouped into {len(data.groups)} '{group_by.value}' bucket(s)."
    return success(data, message)


@router.get(
    "/compare",
    response_model=HistoricalComparisonResponse,
    summary="Compare two historical parameters",
    description=(
        "Compares two sensor and/or derived analytics parameters over "
        "the same time window (e.g. dissolved oxygen vs temperature, "
        "conductivity vs TDS), reporting each series' summary "
        "statistics plus their Pearson correlation coefficient."
    ),
)
def compare_parameters(
    parameter_a: str = Query(..., description="First parameter's sensor or analytics key.", examples=["dissolved_oxygen"]),
    parameter_b: str = Query(..., description="Second parameter's sensor or analytics key.", examples=["temperature"]),
    window: Optional[HistoryWindow] = Query(None, description=_WINDOW_DESCRIPTION),
    start: Optional[datetime] = Query(None, description="Inclusive custom range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive custom range end (ISO 8601)."),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    service: HistoricalAnalyticsService = Depends(get_historical_service_dependency),
) -> HistoricalComparisonResponse:
    """Compare two parameters' historical series over the same window.

    Args:
        parameter_a: The first parameter's key.
        parameter_b: The second parameter's key.
        window: A convenience time-window shortcut.
        start: Inclusive custom range start.
        end: Inclusive custom range end.
        device_name: Optional device filter.
        service: Injected :class:`HistoricalAnalyticsService`.

    Returns:
        A :class:`~app.api.responses.HistoricalComparisonResponse`.

    Raises:
        NotFoundError: If either parameter is unknown.
        BadRequestError: If ``parameter_a`` equals ``parameter_b``, or
            the time-range query parameters conflict.
    """
    if parameter_a == parameter_b:
        raise BadRequestError("'parameter_a' and 'parameter_b' must be different.")

    data: ComparisonData = service.get_comparison(
        parameter_a, parameter_b, window=window, start=start, end=end, device_name=device_name
    )
    message = (
        f"Compared {data.matched_points} aligned sample(s); correlation={data.correlation}"
        if data.matched_points
        else "No overlapping data found for the requested range."
    )
    return success(data, message)
