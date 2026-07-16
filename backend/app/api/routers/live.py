"""Live sensor data endpoints (``/live``).

Serves the latest validated sensor readings only - no analytics, no
history, no aggregation. Values are read directly from
:class:`~app.database.service.DatabaseService`; nothing is computed
here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_sensor_registry_dependency
from app.api.responses import LiveSensorsResponse, success
from app.api.schemas.sensor import LiveSensorReading, LiveSensorsData, QualityStatus
from app.database.models import SensorReading
from app.database.service import DatabaseService, get_database_service
from app.serial.sensor_registry import SensorDefinition, SensorRegistry

router = APIRouter(tags=["Live"])

_INVALID_VALIDATION_STATUSES = frozenset({"invalid", "non_numeric", "unknown_sensor"})


def _derive_quality_status(reading: Optional[SensorReading], definition: SensorDefinition) -> QualityStatus:
    """Classify a reading's coarse quality for display purposes.

    Args:
        reading: The sensor's latest reading, or ``None`` if it has
            never reported a value.
        definition: The sensor's configuration (used for its valid
            physical range).

    Returns:
        The corresponding :class:`~app.api.schemas.sensor.QualityStatus`.
    """
    if reading is None:
        return QualityStatus.NO_DATA
    if reading.validation_status in _INVALID_VALIDATION_STATUSES:
        return QualityStatus.INVALID
    if reading.validation_status == "out_of_range":
        return QualityStatus.OUT_OF_RANGE
    if reading.value is not None and not definition.is_within_range(reading.value):
        return QualityStatus.OUT_OF_RANGE
    return QualityStatus.GOOD


@router.get(
    "/latest",
    response_model=LiveSensorsResponse,
    summary="Latest validated sensor readings",
    description=(
        "Returns the most recent validated reading for every "
        "configured (enabled) sensor. Sensors that have never "
        "reported a value are included with a null value and "
        "'no_data' quality/validation status, so the dashboard can "
        "render a consistent, complete sensor list on every refresh."
    ),
)
def get_latest_live_readings(
    device_name: Optional[str] = Query(
        None,
        description="Restrict readings to a single device. Omit to use the latest reading across all devices.",
        examples=["river-bot-01"],
    ),
    db: DatabaseService = Depends(get_database_service),
    registry: SensorRegistry = Depends(get_sensor_registry_dependency),
) -> LiveSensorsResponse:
    """Fetch the latest reading for every enabled sensor.

    Args:
        device_name: Optional device filter.
        db: Injected database facade.
        registry: Injected sensor registry.

    Returns:
        A :class:`~app.api.responses.LiveSensorsResponse`.
    """
    readings = []
    for definition in registry.enabled_sensors():
        latest = db.get_latest_readings(
            device_name=device_name, sensor_key=definition.sensor_name, limit=1
        )
        reading = latest[0] if latest else None

        readings.append(
            LiveSensorReading(
                sensor_name=definition.sensor_name,
                display_name=definition.display_name,
                value=reading.value if reading is not None else None,
                unit=definition.unit,
                timestamp=reading.timestamp if reading is not None else None,
                quality_status=_derive_quality_status(reading, definition),
                validation_status=reading.validation_status if reading is not None else "no_data",
            )
        )

    data = LiveSensorsData(device_name=device_name, readings=readings)
    return success(data, f"Retrieved latest readings for {len(readings)} sensor(s).")
