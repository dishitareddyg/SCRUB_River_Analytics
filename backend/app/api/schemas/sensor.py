"""Schemas for live sensor data (``GET /live/latest``)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class QualityStatus(str, Enum):
    """Coarse, human-facing quality classification of a live reading.

    Attributes:
        GOOD: The reading validated successfully and falls within the
            sensor's configured physical range.
        OUT_OF_RANGE: The reading validated structurally but its value
            falls outside the sensor's configured
            ``minimum_value``/``maximum_value`` range.
        INVALID: The reading failed validation (e.g. malformed,
            non-numeric, or from an unrecognized sensor field).
        NO_DATA: No reading has ever been recorded for this sensor
            (and device, if filtered).
    """

    GOOD = "good"
    OUT_OF_RANGE = "out_of_range"
    INVALID = "invalid"
    NO_DATA = "no_data"


class LiveSensorReading(BaseModel):
    """A single sensor's most recent validated reading.

    Attributes:
        sensor_name: Canonical machine-readable sensor identifier
            (e.g. ``"dissolved_oxygen"``).
        display_name: Human friendly sensor name.
        value: The latest numeric value, or ``None`` if no reading is
            available yet or the latest reading was non-numeric.
        unit: Unit of measurement (e.g. ``"mg/L"``).
        timestamp: When the latest reading was taken, or ``None`` if
            no reading is available yet.
        quality_status: Coarse quality classification; see
            :class:`QualityStatus`.
        validation_status: The raw validation status string as stored
            by the database layer (e.g. ``"valid"``, ``"invalid"``,
            ``"out_of_range"``), or ``"no_data"`` if no reading exists.
    """

    sensor_name: str = Field(..., examples=["dissolved_oxygen"])
    display_name: str = Field(..., examples=["Dissolved Oxygen"])
    value: Optional[float] = Field(None, examples=[8.42])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    timestamp: Optional[datetime] = Field(None, examples=["2026-07-14T09:30:00Z"])
    quality_status: QualityStatus = Field(..., examples=[QualityStatus.GOOD])
    validation_status: str = Field(..., examples=["valid"])


class LiveSensorsData(BaseModel):
    """Payload for ``GET /live/latest``.

    Attributes:
        device_name: The device filter applied to this request, or
            ``None`` if readings were pulled across all devices.
        readings: One entry per configured (enabled) sensor.
    """

    device_name: Optional[str] = Field(None, examples=["river-bot-01"])
    readings: List[LiveSensorReading] = Field(default_factory=list)
