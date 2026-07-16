"""Pydantic response models for the Historical Analytics & Trend Engine.

These are used directly as the REST API's ``response_model``\\ s (see
``app/api/routers/historical.py``) as well as
:class:`app.historical.service.HistoricalAnalyticsService`'s return
types - kept in this package (rather than under ``app/api/schemas``)
because they describe this module's own data contracts, independent
of any particular transport.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.historical.aggregation import AggregationInterval
from app.historical.seasonal import SeasonalGroupBy
from app.historical.trends import TrendDirection
from app.historical.utils import HistoryWindow

__all__ = [
    "HistoryWindow",
    "AggregationInterval",
    "SeasonalGroupBy",
    "TrendDirection",
    "SeriesMeta",
    "StatisticsData",
    "TrendData",
    "SeasonalGroupData",
    "SeasonalData",
    "AggregatedPointData",
    "AggregationData",
    "ComparisonData",
]


class SeriesMeta(BaseModel):
    """Metadata shared by every historical-analytics response.

    Attributes:
        parameter: The requested parameter key.
        display_name: Human friendly parameter name.
        unit: Unit of measurement, if known.
        source: Either ``"sensor"`` or ``"analytics"`` - see
            :class:`app.historical.utils.ParameterSeries`.
        anchor_sensor: The anchor sensor used to approximate an
            analytics parameter's history, or ``None`` for raw sensor
            parameters (see
            :func:`app.historical.utils.fetch_parameter_series`).
        device_name: The device filter applied, or ``None``.
        start: Start of the analyzed time range (UTC).
        end: End of the analyzed time range (UTC).
        sample_count: Number of usable (non-missing) points analyzed.
        missing_count: Number of readings in range with no usable
            value.
        truncated: Whether the analyzed series was capped at
            :data:`app.historical.utils.MAX_SERIES_POINTS` (oldest
            points beyond the cap were excluded).
    """

    parameter: str = Field(..., examples=["dissolved_oxygen"])
    display_name: str = Field(..., examples=["Dissolved Oxygen"])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    source: str = Field(..., examples=["sensor"])
    anchor_sensor: Optional[str] = Field(None, examples=["conductivity"])
    device_name: Optional[str] = Field(None, examples=["river-bot-01"])
    start: datetime
    end: datetime
    sample_count: int = Field(..., ge=0)
    missing_count: int = Field(..., ge=0)
    truncated: bool = False


class StatisticsData(SeriesMeta):
    """Payload for ``GET /history/statistics/{parameter}``.

    Attributes:
        minimum: Minimum value in range.
        maximum: Maximum value in range.
        average: Mean value in range.
        median: Median value in range.
        std_dev: Sample standard deviation in range.
        variance: Sample variance in range.
        first_value: Earliest value in range.
        last_value: Latest (most recent) value in range.
        percent_change: Percent change from ``first_value`` to
            ``last_value``.
    """

    minimum: Optional[float] = None
    maximum: Optional[float] = None
    average: Optional[float] = None
    median: Optional[float] = None
    std_dev: Optional[float] = None
    variance: Optional[float] = None
    first_value: Optional[float] = None
    last_value: Optional[float] = None
    percent_change: Optional[float] = None


class TrendData(SeriesMeta):
    """Payload for ``GET /history/trends/{parameter}``.

    Attributes:
        direction: The classified qualitative trend.
        trend_percentage: Percent change from the first to the last
            value in range.
        rate_of_change_per_hour: The fitted linear trend's slope,
            expressed as value-change-per-hour.
        slope: The fitted linear trend's raw slope (value per second).
        intercept: The fitted linear trend's intercept.
        trend_confidence: A ``0.0``-``1.0`` confidence score (the
            fitted line's R²) - how well a straight line explains the
            series.
        first_value: Earliest value in range.
        last_value: Latest (most recent) value in range.
    """

    direction: TrendDirection
    trend_percentage: Optional[float] = None
    rate_of_change_per_hour: Optional[float] = None
    slope: Optional[float] = None
    intercept: Optional[float] = None
    trend_confidence: Optional[float] = None
    first_value: Optional[float] = None
    last_value: Optional[float] = None


class SeasonalGroupData(BaseModel):
    """One seasonal group's summary, for API responses.

    Attributes:
        group_key: A stable, sortable key for this group.
        label: A human readable label.
        count: Number of points in this group.
        average: Mean value across the group.
        minimum: Minimum value across the group.
        maximum: Maximum value across the group.
        std_dev: Sample standard deviation across the group.
    """

    group_key: str
    label: str
    count: int = Field(..., ge=0)
    average: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    std_dev: Optional[float] = None


class SeasonalData(SeriesMeta):
    """Payload for ``GET /history/seasonal/{parameter}``.

    Attributes:
        group_by: The calendar dimension groups were computed over.
        groups: One entry per non-empty group.
    """

    group_by: SeasonalGroupBy
    groups: List[SeasonalGroupData] = Field(default_factory=list)


class AggregatedPointData(BaseModel):
    """One aggregated bucket, for API responses.

    Attributes:
        period_start: Inclusive bucket start (UTC).
        period_end: Exclusive bucket end (UTC).
        count: Number of raw points in this bucket.
        average: Mean value across the bucket.
        minimum: Minimum value across the bucket.
        maximum: Maximum value across the bucket.
        std_dev: Sample standard deviation across the bucket.
    """

    period_start: datetime
    period_end: datetime
    count: int = Field(..., ge=0)
    average: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    std_dev: Optional[float] = None


class AggregationData(SeriesMeta):
    """Aggregation result payload (used internally / by future modules).

    Attributes:
        interval: The aggregation bucket size used.
        points: One entry per non-empty bucket, chronologically
            ordered.
    """

    interval: AggregationInterval
    points: List[AggregatedPointData] = Field(default_factory=list)


class ComparisonData(BaseModel):
    """Payload for ``GET /history/compare``.

    Attributes:
        parameter_a: The first parameter's key.
        parameter_b: The second parameter's key.
        display_name_a: The first parameter's human friendly name.
        display_name_b: The second parameter's human friendly name.
        device_name: The device filter applied, or ``None``.
        start: Start of the analyzed time range (UTC).
        end: End of the analyzed time range (UTC).
        sample_count_a: Usable point count for the first parameter.
        sample_count_b: Usable point count for the second parameter.
        matched_points: Number of time-aligned sample pairs the
            correlation was computed from.
        correlation: Pearson correlation coefficient in
            ``[-1.0, 1.0]``, or ``None`` if not computable.
        average_a: Mean value of the first parameter.
        average_b: Mean value of the second parameter.
        minimum_a: Minimum value of the first parameter.
        minimum_b: Minimum value of the second parameter.
        maximum_a: Maximum value of the first parameter.
        maximum_b: Maximum value of the second parameter.
    """

    parameter_a: str = Field(..., examples=["dissolved_oxygen"])
    parameter_b: str = Field(..., examples=["temperature"])
    display_name_a: str
    display_name_b: str
    device_name: Optional[str] = None
    start: datetime
    end: datetime
    sample_count_a: int = Field(..., ge=0)
    sample_count_b: int = Field(..., ge=0)
    matched_points: int = Field(..., ge=0)
    correlation: Optional[float] = None
    average_a: Optional[float] = None
    average_b: Optional[float] = None
    minimum_a: Optional[float] = None
    minimum_b: Optional[float] = None
    maximum_a: Optional[float] = None
    maximum_b: Optional[float] = None
