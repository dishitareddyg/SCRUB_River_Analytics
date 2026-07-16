"""Historical data endpoints (``/history``).

Two endpoints:

    - ``GET /history/sensor/{sensor_name}`` - raw historical sensor
      readings, straight from :class:`~app.database.service.DatabaseService`.
    - ``GET /history/analytics/{parameter}`` - a historical series for
      one derived parameter.

Analytics history approximation
--------------------------------
The Analytics Engine (Module 4) intentionally computes derived
parameters only from the *latest* sensor readings and does not
persist historical derived values (see
:class:`app.analytics.analytics_engine.AnalyticsEngine`). Reconstructing
a fully accurate historical series would require an "as of time T"
value for every input sensor at every historical timestamp, which the
database layer does not expose (and this module must not add to it).

Instead, ``/history/analytics/{parameter}`` uses a documented
approximation: it walks the historical series of the calculator's
*anchor* sensor (its first declared input) and, for every other input
the calculator needs, substitutes a single snapshot of that sensor's
*current* latest value (fetched once, not per point). Each point is
still computed by calling the real, registered calculator from the
Analytics Engine - no formula is reimplemented here. This trades
some historical accuracy on the non-anchor inputs for a bounded,
inexpensive query pattern. The ``anchor_sensor`` used is always
reported in the response so a client can judge relevance.

For an exact, fully-accurate *current* value, use ``interval=latest``
on this endpoint (which delegates directly to
``AnalyticsEngine.compute()``) or ``GET /analytics/latest``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Path, Query

from app.analytics.analytics_engine import DEFAULT_SENSOR_KEY_MAP, AnalyticsEngine
from app.analytics.calculator_registry import get_calculator
from app.analytics.config import AnalyticsConfig
from app.api.dependencies import get_analytics_config_dependency, get_sensor_registry_dependency
from app.api.responses import AnalyticsHistoryResponse, SensorHistoryResponse, success
from app.api.schemas.analytics import AnalyticsHistoryData, AnalyticsHistoryPoint
from app.api.schemas.history import HistoryInterval, SensorHistoryData, SensorHistoryPoint
from app.database.service import DatabaseService, get_database_service
from app.serial.sensor_registry import SensorRegistry
from app.utils.exceptions import BadRequestError, NotFoundError

router = APIRouter(tags=["History"])

_INTERVAL_DELTAS: Dict[HistoryInterval, timedelta] = {
    HistoryInterval.HOUR: timedelta(hours=1),
    HistoryInterval.DAY: timedelta(days=1),
    HistoryInterval.WEEK: timedelta(weeks=1),
    HistoryInterval.MONTH: timedelta(days=30),
}
_DEFAULT_RANGE = timedelta(days=1)


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


def _resolve_time_range(
    start: Optional[datetime], end: Optional[datetime], interval: Optional[HistoryInterval]
) -> Tuple[datetime, datetime, bool]:
    """Resolve the effective ``(start, end)`` range for a history query.

    Args:
        start: Explicit inclusive range start, if provided.
        end: Explicit inclusive range end, if provided.
        interval: A convenience shortcut, mutually exclusive with
            ``start``/``end``.

    Returns:
        A ``(start, end, is_latest)`` tuple. When ``is_latest`` is
        ``True``, ``start``/``end`` are both "now" and callers should
        fetch only the single latest reading rather than a ranged
        query.

    Raises:
        BadRequestError: If ``interval`` is combined with ``start``/
            ``end``, if only one of ``start``/``end`` is supplied, or
            if ``start`` is not strictly before ``end``.
    """
    start = _as_utc(start)
    end = _as_utc(end)
    now = datetime.now(timezone.utc)

    if interval is not None and (start is not None or end is not None):
        raise BadRequestError(
            "Specify either 'interval' or 'start'/'end', not both."
        )

    if interval is not None:
        if interval is HistoryInterval.LATEST:
            return now, now, True
        return now - _INTERVAL_DELTAS[interval], now, False

    if (start is None) != (end is None):
        raise BadRequestError("Both 'start' and 'end' are required when either is provided.")

    if start is not None and end is not None:
        if start >= end:
            raise BadRequestError("'start' must be strictly before 'end'.")
        return start, end, False

    # Neither interval nor an explicit range was given: default to the last day.
    return now - _DEFAULT_RANGE, now, False


@router.get(
    "/sensor/{sensor_name}",
    response_model=SensorHistoryResponse,
    summary="Historical sensor readings",
    description=(
        "Returns historical readings for one sensor. Supply either "
        "'interval' (latest/hour/day/week/month) or an explicit "
        "'start'/'end' range, not both; defaults to the last day if "
        "neither is given. Results are paginated and ordered oldest "
        "first."
    ),
)
def get_sensor_history(
    sensor_name: str = Path(..., description="Canonical sensor key.", examples=["dissolved_oxygen"]),
    start: Optional[datetime] = Query(None, description="Inclusive range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive range end (ISO 8601)."),
    interval: Optional[HistoryInterval] = Query(
        None, description="Convenience shortcut; mutually exclusive with start/end."
    ),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(500, ge=1, le=5000, description="Maximum records per page."),
    registry: SensorRegistry = Depends(get_sensor_registry_dependency),
    db: DatabaseService = Depends(get_database_service),
) -> SensorHistoryResponse:
    """Fetch historical readings for one sensor.

    Args:
        sensor_name: The sensor's canonical key.
        start: Inclusive range start.
        end: Inclusive range end.
        interval: Convenience range shortcut.
        device_name: Optional device filter.
        page: 1-indexed page number.
        page_size: Maximum records per page.
        registry: Injected sensor registry.
        db: Injected database facade.

    Returns:
        A :class:`~app.api.responses.SensorHistoryResponse`.

    Raises:
        NotFoundError: If ``sensor_name`` is not a configured sensor.
        BadRequestError: If the time-range query parameters conflict.
    """
    definition = registry.get(sensor_name)
    if definition is None:
        raise NotFoundError(f"Unknown sensor '{sensor_name}'.")

    resolved_start, resolved_end, is_latest = _resolve_time_range(start, end, interval)

    if is_latest:
        latest = db.get_latest_readings(device_name=device_name, sensor_key=sensor_name, limit=1)
        points = [
            SensorHistoryPoint(timestamp=r.timestamp, value=r.value, validation_status=r.validation_status)
            for r in latest
        ]
        data = SensorHistoryData(
            sensor_name=definition.sensor_name,
            display_name=definition.display_name,
            unit=definition.unit,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            page=1,
            page_size=max(len(points), 1),
            total=len(points),
            total_pages=1,
            points=points,
        )
    else:
        history_page = db.get_sensor_history(
            sensor_key=sensor_name,
            start=resolved_start,
            end=resolved_end,
            device_name=device_name,
            page=page,
            page_size=page_size,
        )
        points = [
            SensorHistoryPoint(timestamp=r.timestamp, value=r.value, validation_status=r.validation_status)
            for r in history_page.items
        ]
        data = SensorHistoryData(
            sensor_name=definition.sensor_name,
            display_name=definition.display_name,
            unit=definition.unit,
            device_name=device_name,
            start=resolved_start,
            end=resolved_end,
            page=history_page.page,
            page_size=history_page.page_size,
            total=history_page.total,
            total_pages=history_page.total_pages,
            points=points,
        )

    message = f"Retrieved {len(points)} reading(s)." if points else "No readings found for the requested range."
    return success(data, message)


@router.get(
    "/analytics/{parameter}",
    response_model=AnalyticsHistoryResponse,
    summary="Historical derived-analytics series",
    description=(
        "Returns a historical series for one derived parameter, "
        "recomputed via the Analytics Engine from the historical "
        "readings of the parameter's anchor input sensor (see this "
        "router module's docstring for the exact approximation used). "
        "Use interval=latest for an exact, fully-accurate current "
        "value instead."
    ),
)
def get_analytics_history(
    parameter: str = Path(..., description="Registered analytics parameter key.", examples=["tds"]),
    start: Optional[datetime] = Query(None, description="Inclusive range start (ISO 8601)."),
    end: Optional[datetime] = Query(None, description="Inclusive range end (ISO 8601)."),
    interval: Optional[HistoryInterval] = Query(
        None, description="Convenience shortcut; mutually exclusive with start/end."
    ),
    device_name: Optional[str] = Query(None, description="Restrict to a single device."),
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(200, ge=1, le=2000, description="Maximum points per page."),
    db: DatabaseService = Depends(get_database_service),
    config: AnalyticsConfig = Depends(get_analytics_config_dependency),
) -> AnalyticsHistoryResponse:
    """Fetch a historical series for one derived parameter.

    Args:
        parameter: The calculator's registry key.
        start: Inclusive range start.
        end: Inclusive range end.
        interval: Convenience range shortcut.
        device_name: Optional device filter.
        page: 1-indexed page number.
        page_size: Maximum points per page.
        db: Injected database facade.
        config: Injected Analytics Engine configuration.

    Returns:
        An :class:`~app.api.responses.AnalyticsHistoryResponse`.

    Raises:
        NotFoundError: If ``parameter`` is not a registered calculator.
        BadRequestError: If the time-range query parameters conflict,
            or the calculator declares no inputs to chart against.
    """
    try:
        calculator = get_calculator(parameter)
    except KeyError as exc:
        raise NotFoundError(f"Unknown analytics parameter '{parameter}'.") from exc

    metadata = calculator.metadata()
    all_inputs: List[str] = list(metadata.required_inputs) + [
        name for name in metadata.optional_inputs if name not in metadata.required_inputs
    ]
    if not all_inputs:
        raise BadRequestError(f"Analytics parameter '{parameter}' has no sensor inputs to chart.")

    anchor_input = all_inputs[0]
    anchor_sensor_key = DEFAULT_SENSOR_KEY_MAP.get(anchor_input, anchor_input)

    resolved_start, resolved_end, is_latest = _resolve_time_range(start, end, interval)

    if is_latest:
        engine = AnalyticsEngine(database_service=db, config=config)
        result = engine.compute(parameter, device_name=device_name)
        points = [
            AnalyticsHistoryPoint(
                timestamp=result.timestamp,
                value=result.value,
                status=result.status.value,
                warnings=result.warnings,
            )
        ]
        data = AnalyticsHistoryData(
            parameter=parameter,
            display_name=metadata.display_name,
            unit=metadata.output_unit,
            anchor_sensor=anchor_sensor_key,
            start=resolved_start,
            end=resolved_end,
            page=1,
            page_size=1,
            total=1,
            total_pages=1,
            points=points,
        )
        return success(data, f"Computed the latest value for '{parameter}'.")

    anchor_page = db.get_sensor_history(
        sensor_key=anchor_sensor_key,
        start=resolved_start,
        end=resolved_end,
        device_name=device_name,
        page=page,
        page_size=page_size,
    )

    other_inputs = [name for name in all_inputs if name != anchor_input]
    snapshot_inputs: Dict[str, Optional[float]] = {}
    for input_name in other_inputs:
        sensor_key = DEFAULT_SENSOR_KEY_MAP.get(input_name, input_name)
        latest = db.get_latest_readings(device_name=device_name, sensor_key=sensor_key, limit=1)
        snapshot_inputs[input_name] = latest[0].value if latest else None

    points = []
    for reading in anchor_page.items:
        inputs = dict(snapshot_inputs)
        inputs[anchor_input] = reading.value
        point_result = calculator.calculate(inputs, config)
        points.append(
            AnalyticsHistoryPoint(
                timestamp=reading.timestamp,
                value=point_result.value,
                status=point_result.status.value,
                warnings=point_result.warnings,
            )
        )

    data = AnalyticsHistoryData(
        parameter=parameter,
        display_name=metadata.display_name,
        unit=metadata.output_unit,
        anchor_sensor=anchor_sensor_key,
        start=resolved_start,
        end=resolved_end,
        page=anchor_page.page,
        page_size=anchor_page.page_size,
        total=anchor_page.total,
        total_pages=anchor_page.total_pages,
        points=points,
    )
    message = (
        f"Recomputed {len(points)} historical point(s) for '{parameter}'."
        if points
        else "No anchor-sensor readings found for the requested range."
    )
    return success(data, message)
