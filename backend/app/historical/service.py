"""The Historical Analytics & Trend Engine's public façade.

:class:`HistoricalAnalyticsService` is the single entry point the API
layer (and any future module, e.g. the forecasting/ML module planned
next) should depend on. It composes:

    * :mod:`app.historical.utils` for time-window resolution and
      fetching a parameter's in-range series.
    * :mod:`app.historical.statistics` for summary statistics.
    * :mod:`app.historical.trends` for trend classification.
    * :mod:`app.historical.seasonal` for seasonal grouping.
    * :mod:`app.historical.aggregation` for bucketed aggregation.
    * :mod:`app.historical.comparison` for two-parameter comparison.

Every dependency (`DatabaseService`, `SensorRegistry`,
`AnalyticsConfig`) is injected through the constructor rather than
imported as a module-level singleton, per this module's Dependency
Injection coding standard - this keeps the service trivially testable
against an isolated in-memory database, exactly like every other
service in this codebase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.database.service import DatabaseService, get_database_service
from app.historical import statistics as stats
from app.historical.aggregation import AggregationInterval, aggregate_series
from app.historical.comparison import compare_series
from app.historical.schemas import (
    AggregatedPointData,
    AggregationData,
    ComparisonData,
    SeasonalData,
    SeasonalGroupData,
    StatisticsData,
    TrendData,
)
from app.historical.seasonal import SeasonalGroupBy, group_seasonal
from app.historical.trends import (
    classify_trend,
    linear_trend,
    rate_of_change,
    trend_confidence,
    trend_percentage,
)
from app.historical.utils import HistoryWindow, ParameterSeries, fetch_parameter_series, resolve_time_window
from app.serial.sensor_registry import SensorRegistry, get_sensor_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


class HistoricalAnalyticsService:
    """Reusable service computing historical statistics/trends/seasonality.

    Attributes:
        db: The injected database facade.
        sensor_registry: The injected configured sensor registry.
        analytics_config: The injected Analytics Engine configuration
            (needed to recompute derived-parameter history).
    """

    def __init__(
        self,
        db: Optional[DatabaseService] = None,
        sensor_registry: Optional[SensorRegistry] = None,
        analytics_config: Optional[AnalyticsConfig] = None,
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
        """
        self.db = db or get_database_service()
        self.sensor_registry = sensor_registry or get_sensor_registry()
        self.analytics_config = analytics_config or get_analytics_config()

    # ------------------------------------------------------------------
    # Shared fetch
    # ------------------------------------------------------------------

    def _resolve_series(
        self,
        parameter: str,
        window: Optional[HistoryWindow],
        start: Optional[datetime],
        end: Optional[datetime],
        device_name: Optional[str],
    ) -> Tuple[ParameterSeries, datetime, datetime]:
        """Resolve the time range and fetch a parameter's in-range series.

        Args:
            parameter: A sensor's canonical key, or a registered
                analytics calculator key.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A ``(series, resolved_start, resolved_end)`` tuple.

        Raises:
            NotFoundError: If ``parameter`` is unknown.
            BadRequestError: If the time-range parameters conflict.
        """
        resolved_start, resolved_end = resolve_time_window(window, start, end)
        logger.info(
            f"Historical fetch: parameter={parameter!r} start={resolved_start.isoformat()} "
            f"end={resolved_end.isoformat()} device={device_name!r}"
        )
        series = fetch_parameter_series(
            self.db,
            self.sensor_registry,
            self.analytics_config,
            parameter,
            resolved_start,
            resolved_end,
            device_name,
        )
        return series, resolved_start, resolved_end

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(
        self,
        parameter: str,
        window: Optional[HistoryWindow] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        device_name: Optional[str] = None,
    ) -> StatisticsData:
        """Compute summary statistics for a parameter over a time window.

        Args:
            parameter: A sensor's canonical key, or a registered
                analytics calculator key.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.historical.schemas.StatisticsData`.
        """
        series, resolved_start, resolved_end = self._resolve_series(parameter, window, start, end, device_name)
        values = [value for _, value in series.points]

        result = StatisticsData(
            parameter=series.parameter,
            display_name=series.display_name,
            unit=series.unit,
            source=series.source,
            anchor_sensor=series.anchor_sensor,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            sample_count=len(values),
            missing_count=series.missing_count,
            truncated=series.truncated,
            minimum=stats.minimum(values),
            maximum=stats.maximum(values),
            average=stats.average(values),
            median=stats.median(values),
            std_dev=stats.std_dev(values),
            variance=stats.variance(values),
            first_value=stats.first_value(values),
            last_value=stats.last_value(values),
            percent_change=stats.percent_change(stats.first_value(values), stats.last_value(values)),
        )
        logger.info(f"Statistics computed: parameter={parameter!r} sample_count={result.sample_count}")
        return result

    # ------------------------------------------------------------------
    # Trends
    # ------------------------------------------------------------------

    def get_trends(
        self,
        parameter: str,
        window: Optional[HistoryWindow] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        device_name: Optional[str] = None,
    ) -> TrendData:
        """Classify the trend of a parameter over a time window.

        Args:
            parameter: A sensor's canonical key, or a registered
                analytics calculator key.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.historical.schemas.TrendData`.
        """
        series, resolved_start, resolved_end = self._resolve_series(parameter, window, start, end, device_name)
        values = [value for _, value in series.points]

        first = stats.first_value(values)
        last = stats.last_value(values)
        change_percent = trend_percentage(first, last)

        if series.points:
            window_start_ts = series.points[0][0]
            regression_points = [
                ((timestamp - window_start_ts).total_seconds(), value) for timestamp, value in series.points
            ]
        else:
            regression_points = []

        fitted = linear_trend(regression_points)

        result = TrendData(
            parameter=series.parameter,
            display_name=series.display_name,
            unit=series.unit,
            source=series.source,
            anchor_sensor=series.anchor_sensor,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            sample_count=len(values),
            missing_count=series.missing_count,
            truncated=series.truncated,
            direction=classify_trend(change_percent),
            trend_percentage=change_percent,
            rate_of_change_per_hour=rate_of_change(fitted, seconds_per_unit=3600.0),
            slope=fitted.slope if fitted else None,
            intercept=fitted.intercept if fitted else None,
            trend_confidence=trend_confidence(fitted),
            first_value=first,
            last_value=last,
        )
        logger.info(f"Trend computed: parameter={parameter!r} direction={result.direction.value}")
        return result

    # ------------------------------------------------------------------
    # Seasonal
    # ------------------------------------------------------------------

    def get_seasonal(
        self,
        parameter: str,
        group_by: SeasonalGroupBy,
        window: Optional[HistoryWindow] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        device_name: Optional[str] = None,
    ) -> SeasonalData:
        """Group a parameter's history by a calendar dimension.

        Args:
            parameter: A sensor's canonical key, or a registered
                analytics calculator key.
            group_by: The calendar dimension to group by.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.historical.schemas.SeasonalData`.
        """
        series, resolved_start, resolved_end = self._resolve_series(parameter, window, start, end, device_name)
        group_summaries = group_seasonal(series.points, group_by)

        result = SeasonalData(
            parameter=series.parameter,
            display_name=series.display_name,
            unit=series.unit,
            source=series.source,
            anchor_sensor=series.anchor_sensor,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            sample_count=len(series.points),
            missing_count=series.missing_count,
            truncated=series.truncated,
            group_by=group_by,
            groups=[
                SeasonalGroupData(
                    group_key=g.group_key,
                    label=g.label,
                    count=g.count,
                    average=g.average,
                    minimum=g.minimum,
                    maximum=g.maximum,
                    std_dev=g.std_dev,
                )
                for g in group_summaries
            ],
        )
        logger.info(f"Seasonal grouping computed: parameter={parameter!r} groups={len(result.groups)}")
        return result

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def get_aggregation(
        self,
        parameter: str,
        interval: AggregationInterval,
        window: Optional[HistoryWindow] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        device_name: Optional[str] = None,
    ) -> AggregationData:
        """Aggregate a parameter's history into fixed-size buckets.

        Reusable building block for future modules (e.g. an ML module
        wanting hourly/daily features) - not currently exposed as its
        own REST endpoint, but built on the same shared fetch path as
        every other method here.

        Args:
            parameter: A sensor's canonical key, or a registered
                analytics calculator key.
            interval: The aggregation bucket size.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.historical.schemas.AggregationData`.
        """
        series, resolved_start, resolved_end = self._resolve_series(parameter, window, start, end, device_name)
        buckets = aggregate_series(series.points, interval)

        result = AggregationData(
            parameter=series.parameter,
            display_name=series.display_name,
            unit=series.unit,
            source=series.source,
            anchor_sensor=series.anchor_sensor,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            sample_count=len(series.points),
            missing_count=series.missing_count,
            truncated=series.truncated,
            interval=interval,
            points=[
                AggregatedPointData(
                    period_start=b.period_start,
                    period_end=b.period_end,
                    count=b.count,
                    average=b.average,
                    minimum=b.minimum,
                    maximum=b.maximum,
                    std_dev=b.std_dev,
                )
                for b in buckets
            ],
        )
        logger.info(f"Aggregation computed: parameter={parameter!r} buckets={len(result.points)}")
        return result

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def get_comparison(
        self,
        parameter_a: str,
        parameter_b: str,
        window: Optional[HistoryWindow] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        device_name: Optional[str] = None,
    ) -> ComparisonData:
        """Compare two parameters' historical series (e.g. correlation).

        Args:
            parameter_a: The first parameter's key.
            parameter_b: The second parameter's key.
            window: A convenience time-window shortcut.
            start: Inclusive custom range start.
            end: Inclusive custom range end.
            device_name: Optional device filter.

        Returns:
            A populated :class:`~app.historical.schemas.ComparisonData`.

        Raises:
            NotFoundError: If either parameter is unknown.
            BadRequestError: If the time-range parameters conflict.
        """
        series_a, resolved_start, resolved_end = self._resolve_series(parameter_a, window, start, end, device_name)
        # Re-use the exact same resolved range for both parameters so
        # they're compared over an identical window.
        series_b = fetch_parameter_series(
            self.db,
            self.sensor_registry,
            self.analytics_config,
            parameter_b,
            resolved_start,
            resolved_end,
            device_name,
        )

        comparison = compare_series(series_a.points, series_b.points)

        result = ComparisonData(
            parameter_a=series_a.parameter,
            parameter_b=series_b.parameter,
            display_name_a=series_a.display_name,
            display_name_b=series_b.display_name,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            sample_count_a=comparison.parameter_a.count,
            sample_count_b=comparison.parameter_b.count,
            matched_points=comparison.matched_points,
            correlation=comparison.correlation,
            average_a=comparison.parameter_a.average,
            average_b=comparison.parameter_b.average,
            minimum_a=comparison.parameter_a.minimum,
            minimum_b=comparison.parameter_b.minimum,
            maximum_a=comparison.parameter_a.maximum,
            maximum_b=comparison.parameter_b.maximum,
        )
        logger.info(
            f"Comparison computed: a={parameter_a!r} b={parameter_b!r} "
            f"matched_points={result.matched_points} correlation={result.correlation}"
        )
        return result


__all__ = ["HistoricalAnalyticsService"]
