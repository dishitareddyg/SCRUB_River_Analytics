"""Schemas for historical data (``/history``)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class HistoryInterval(str, Enum):
    """A convenience shortcut for a common historical time range.

    Mutually exclusive with explicitly supplying ``start``/``end`` -
    see each history endpoint's query parameters.

    Attributes:
        LATEST: Just the single most recent reading (no time range).
        HOUR: The last hour.
        DAY: The last 24 hours.
        WEEK: The last 7 days.
        MONTH: The last 30 days.
    """

    LATEST = "latest"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class SensorHistoryPoint(BaseModel):
    """A single historical sensor reading.

    Attributes:
        timestamp: When the reading was taken.
        value: The numeric value, or ``None`` for a non-numeric/compound
            reading.
        validation_status: The stored validation outcome (e.g.
            ``"valid"``, ``"invalid"``, ``"out_of_range"``).
    """

    timestamp: datetime
    value: Optional[float] = None
    validation_status: str


class SensorHistoryData(BaseModel):
    """Payload for ``GET /history/sensor/{sensor_name}``.

    Attributes:
        sensor_name: The requested sensor's canonical key.
        display_name: Human friendly sensor name.
        unit: Unit of measurement.
        device_name: The device filter applied to this request, or
            ``None``.
        start: Start of the returned time range.
        end: End of the returned time range.
        page: 1-indexed page number returned.
        page_size: Maximum records requested per page.
        total: Total number of matching readings across all pages.
        total_pages: Total number of pages available.
        points: The readings on this page, oldest first.
    """

    sensor_name: str = Field(..., examples=["dissolved_oxygen"])
    display_name: str = Field(..., examples=["Dissolved Oxygen"])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    device_name: Optional[str] = Field(None, examples=["river-bot-01"])
    start: datetime
    end: datetime
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=1)
    points: List[SensorHistoryPoint] = Field(default_factory=list)
