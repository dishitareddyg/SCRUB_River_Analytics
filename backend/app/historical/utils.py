"""Shared time-window resolution and the parameter data-fetching helper.

Every service method in :mod:`app.historical.service` needs the same
two things first: (1) turn a requested time window into a concrete
``(start, end)`` range, and (2) fetch that range's data points for a
named "parameter" - which may be a raw sensor or a derived analytics
parameter. Both concerns live here so they're implemented exactly
once (see this module's "No Duplicate Logic" coding standard).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.analytics.analytics_engine import DEFAULT_SENSOR_KEY_MAP
from app.analytics.calculator_registry import get_calculator, is_registered
from app.analytics.config import AnalyticsConfig
from app.database.service import DatabaseService
from app.serial.sensor_registry import SensorRegistry
from app.utils.exceptions import BadRequestError, NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Hard cap on how many raw points a single request will fetch/hold in
#: memory, regardless of the requested window. Bounds both query cost
#: and the size of the in-memory statistics computation, per this
#: module's "several years of historical data" performance
#: requirement. A request that would exceed this is not an error - it
#: is silently (but loggedly) truncated to the most recent
#: ``MAX_SERIES_POINTS`` points in range.
MAX_SERIES_POINTS = 20_000

#: Page size used internally when paging through
#: ``DatabaseService.get_sensor_history`` - large enough to keep the
#: number of round trips small, small enough to keep any one query
#: response modest.
_FETCH_PAGE_SIZE = 2_000


class HistoryWindow(str, Enum):
    """A supported convenience time-window shortcut.

    Mutually exclusive with supplying an explicit ``start``/``end``
    custom range - see :func:`resolve_time_window`.

    Attributes:
        HOUR: The last hour.
        DAY: The last 24 hours.
        WEEK: The last 7 days.
        MONTH: The last 30 days.
        QUARTER: The last 90 days.
        YEAR: The last 365 days.
    """

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


_WINDOW_DELTAS: Dict[HistoryWindow, timedelta] = {
    HistoryWindow.HOUR: timedelta(hours=1),
    HistoryWindow.DAY: timedelta(days=1),
    HistoryWindow.WEEK: timedelta(weeks=1),
    HistoryWindow.MONTH: timedelta(days=30),
    HistoryWindow.QUARTER: timedelta(days=90),
    HistoryWindow.YEAR: timedelta(days=365),
}

_DEFAULT_WINDOW = HistoryWindow.DAY


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize a possibly-naive datetime to UTC.

    Args:
        value: A datetime, or ``None``.

    Returns:
        ``None`` if ``value`` is ``None``; otherwise ``value`` with
        UTC attached if it had no timezone info, unchanged otherwise.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def resolve_time_window(
    window: Optional[HistoryWindow], start: Optional[datetime], end: Optional[datetime]
) -> Tuple[datetime, datetime]:
    """Resolve the effective ``(start, end)`` range for a historical query.

    Args:
        window: A convenience shortcut (e.g. "last 7 days"), mutually
            exclusive with ``start``/``end``.
        start: Inclusive custom range start.
        end: Inclusive custom range end.

    Returns:
        A concrete ``(start, end)`` tuple, both timezone-aware UTC.

    Raises:
        BadRequestError: If ``window`` is combined with ``start``/
            ``end``, if only one of ``start``/``end`` is supplied, or
            if ``start`` is not strictly before ``end``.
    """
    start = _as_utc(start)
    end = _as_utc(end)
    now = datetime.now(timezone.utc)

    if window is not None and (start is not None or end is not None):
        raise BadRequestError("Specify either 'window' or 'start'/'end' (custom range), not both.")

    if window is not None:
        return now - _WINDOW_DELTAS[window], now

    if (start is None) != (end is None):
        raise BadRequestError("Both 'start' and 'end' are required for a custom range.")

    if start is not None and end is not None:
        if start >= end:
            raise BadRequestError("'start' must be strictly before 'end'.")
        return start, end

    # Neither a window nor a custom range was given: default window.
    return now - _WINDOW_DELTAS[_DEFAULT_WINDOW], now


@dataclass
class ParameterSeries:
    """A resolved, in-memory historical series for one parameter.

    Attributes:
        parameter: The requested parameter key, as given.
        source: Either ``"sensor"`` (a raw sensor channel) or
            ``"analytics"`` (a derived parameter, recomputed via the
            Analytics Engine).
        display_name: Human friendly name.
        unit: Unit of measurement, if known.
        anchor_sensor: For ``source == "analytics"`` series, the
            sensor whose historical readings drove this series (see
            the module docstring on the anchor-sensor approximation).
            ``None`` for raw sensor series.
        points: ``(timestamp, value)`` pairs, oldest first, with
            non-numeric/unreadable entries already dropped.
        missing_count: Number of readings in range whose value was
            ``None``/unreadable (and therefore excluded from
            ``points``).
        total_in_range: Total number of raw readings found in range,
            before the :data:`MAX_SERIES_POINTS` truncation (if any)
            was applied and before dropping missing values.
        truncated: Whether ``points`` was capped by
            :data:`MAX_SERIES_POINTS` (i.e. ``total_in_range`` exceeds
            what was actually fetched).
    """

    parameter: str
    source: str
    display_name: str
    unit: Optional[str]
    anchor_sensor: Optional[str]
    points: List[Tuple[datetime, float]] = field(default_factory=list)
    missing_count: int = 0
    total_in_range: int = 0
    truncated: bool = False


def _fetch_sensor_points(
    db: DatabaseService,
    sensor_key: str,
    start: datetime,
    end: datetime,
    device_name: Optional[str],
) -> Tuple[List[Tuple[datetime, float]], int, int, bool]:
    """Page through a sensor's raw history within a time range.

    Args:
        db: The database facade.
        sensor_key: The sensor's canonical key.
        start: Inclusive range start.
        end: Inclusive range end.
        device_name: Optional device filter.

    Returns:
        A ``(points, missing_count, total_in_range, truncated)`` tuple.
    """
    points: List[Tuple[datetime, float]] = []
    missing_count = 0
    page = 1
    total_in_range = 0
    truncated = False

    while True:
        result = db.get_sensor_history(
            sensor_key=sensor_key,
            start=start,
            end=end,
            device_name=device_name,
            page=page,
            page_size=_FETCH_PAGE_SIZE,
        )
        total_in_range = result.total

        for reading in result.items:
            if len(points) >= MAX_SERIES_POINTS:
                truncated = True
                break
            if reading.value is None:
                missing_count += 1
            else:
                points.append((reading.timestamp, reading.value))

        if truncated or page >= result.total_pages:
            break
        page += 1

    return points, missing_count, total_in_range, truncated


def _fetch_analytics_points(
    db: DatabaseService,
    parameter: str,
    start: datetime,
    end: datetime,
    device_name: Optional[str],
    config: AnalyticsConfig,
) -> Tuple[List[Tuple[datetime, float]], int, int, bool, str]:
    """Recompute a derived parameter's historical series from its anchor sensor.

    Mirrors the documented approximation used by
    ``GET /history/analytics/{parameter}``
    (:mod:`app.api.routers.history`): walks the calculator's anchor
    (first declared) input sensor's historical series and, for every
    other input, substitutes one snapshot of that sensor's current
    latest value. Every point is still produced by calling the real,
    registered calculator - no formula is reimplemented here.

    Args:
        db: The database facade.
        parameter: The calculator's registry key.
        start: Inclusive range start.
        end: Inclusive range end.
        device_name: Optional device filter.
        config: The active :class:`AnalyticsConfig`.

    Returns:
        A ``(points, missing_count, total_in_range, truncated,
        anchor_sensor)`` tuple.

    Raises:
        BadRequestError: If the calculator declares no sensor inputs.
    """
    calculator = get_calculator(parameter)
    metadata = calculator.metadata()
    all_inputs = list(metadata.required_inputs) + [
        name for name in metadata.optional_inputs if name not in metadata.required_inputs
    ]
    if not all_inputs:
        raise BadRequestError(f"Analytics parameter '{parameter}' has no sensor inputs to chart.")

    anchor_input = all_inputs[0]
    anchor_sensor_key = DEFAULT_SENSOR_KEY_MAP.get(anchor_input, anchor_input)

    anchor_points_raw, missing_count, total_in_range, truncated = _fetch_sensor_points(
        db, anchor_sensor_key, start, end, device_name
    )

    other_inputs = [name for name in all_inputs if name != anchor_input]
    snapshot_inputs: Dict[str, Optional[float]] = {}
    for input_name in other_inputs:
        sensor_key = DEFAULT_SENSOR_KEY_MAP.get(input_name, input_name)
        latest = db.get_latest_readings(device_name=device_name, sensor_key=sensor_key, limit=1)
        snapshot_inputs[input_name] = latest[0].value if latest else None

    points: List[Tuple[datetime, float]] = []
    for timestamp, anchor_value in anchor_points_raw:
        inputs = dict(snapshot_inputs)
        inputs[anchor_input] = anchor_value
        result = calculator.calculate(inputs, config)
        if result.value is not None:
            points.append((timestamp, result.value))
        else:
            missing_count += 1

    return points, missing_count, total_in_range, truncated, anchor_sensor_key


def fetch_parameter_series(
    db: DatabaseService,
    sensor_registry: SensorRegistry,
    config: AnalyticsConfig,
    parameter: str,
    start: datetime,
    end: datetime,
    device_name: Optional[str] = None,
) -> ParameterSeries:
    """Resolve ``parameter`` (sensor or derived) and fetch its in-range series.

    Args:
        db: The database facade.
        sensor_registry: The configured sensor registry.
        config: The active :class:`AnalyticsConfig`.
        parameter: A sensor's canonical key, or a registered analytics
            calculator key.
        start: Inclusive range start.
        end: Inclusive range end.
        device_name: Optional device filter.

    Returns:
        A populated :class:`ParameterSeries`.

    Raises:
        NotFoundError: If ``parameter`` is neither a known sensor nor
            a registered analytics parameter.
        BadRequestError: If ``parameter`` resolves to an analytics
            calculator with no sensor inputs to chart.
    """
    sensor_definition = sensor_registry.get(parameter)
    if sensor_definition is not None:
        points, missing_count, total_in_range, truncated = _fetch_sensor_points(
            db, parameter, start, end, device_name
        )
        if truncated:
            logger.warning(
                f"Historical series for sensor '{parameter}' truncated to "
                f"{MAX_SERIES_POINTS} points (in range: {total_in_range})."
            )
        return ParameterSeries(
            parameter=parameter,
            source="sensor",
            display_name=sensor_definition.display_name,
            unit=sensor_definition.unit,
            anchor_sensor=None,
            points=points,
            missing_count=missing_count,
            total_in_range=total_in_range,
            truncated=truncated,
        )

    if is_registered(parameter):
        points, missing_count, total_in_range, truncated, anchor_sensor = _fetch_analytics_points(
            db, parameter, start, end, device_name, config
        )
        if truncated:
            logger.warning(
                f"Historical series for analytics parameter '{parameter}' truncated to "
                f"{MAX_SERIES_POINTS} points (in range: {total_in_range})."
            )
        metadata = get_calculator(parameter).metadata()
        return ParameterSeries(
            parameter=parameter,
            source="analytics",
            display_name=metadata.display_name,
            unit=metadata.output_unit,
            anchor_sensor=anchor_sensor,
            points=points,
            missing_count=missing_count,
            total_in_range=total_in_range,
            truncated=truncated,
        )

    raise NotFoundError(f"Unknown parameter '{parameter}' (not a configured sensor or analytics key).")


__all__ = [
    "HistoryWindow",
    "ParameterSeries",
    "MAX_SERIES_POINTS",
    "resolve_time_window",
    "fetch_parameter_series",
]
