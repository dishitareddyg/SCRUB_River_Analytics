"""Schemas for derived-analytics data (``/analytics``).

Every field here mirrors
:class:`app.analytics.result.CalculationResult` - this module never
computes anything itself, it only shapes the Analytics Engine's own
output into an API response.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AnalyticsStatus(str, Enum):
    """Mirrors :class:`app.analytics.result.CalculationStatus` for API responses."""

    OK = "OK"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"
    ERROR = "ERROR"


class AnalyticsResult(BaseModel):
    """A single derived parameter's calculation outcome.

    Attributes:
        parameter: The calculator's registry key (e.g. ``"tds"``).
        display_name: Human friendly parameter name.
        status: The calculation outcome.
        value: The computed value, or ``None`` if not computable/errored.
        unit: Unit of ``value`` (e.g. ``"mg/L"``).
        timestamp: When the calculation was performed (UTC).
        confidence: A ``0.0``-``1.0`` confidence score, or ``None``.
        formula_used: Human readable formula name.
        reference: The scientific/engineering reference for the formula.
        missing_inputs: Names of any required inputs/configuration
            that were unavailable.
        warnings: Non-fatal warnings raised during calculation.
        error_message: Populated only when ``status`` is ``ERROR``.
    """

    parameter: str = Field(..., examples=["tds"])
    display_name: str = Field(..., examples=["Total Dissolved Solids"])
    status: AnalyticsStatus = Field(..., examples=[AnalyticsStatus.OK])
    value: Optional[float] = Field(None, examples=[325.0])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    timestamp: datetime = Field(..., examples=["2026-07-14T09:30:00Z"])
    confidence: Optional[float] = Field(None, examples=[0.8])
    formula_used: Optional[str] = Field(
        None, examples=["Conductivity-to-TDS empirical conversion (Hem, 1985)"]
    )
    reference: Optional[str] = Field(None, examples=["Hem, J.D. (1985), USGS Water-Supply Paper 2254."])
    missing_inputs: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class AnalyticsLatestData(BaseModel):
    """Payload for ``GET /analytics/latest``.

    Attributes:
        device_name: The device filter applied to this request, or
            ``None`` if the latest readings were pulled across all
            devices.
        results: One entry per registered derived parameter.
    """

    device_name: Optional[str] = Field(None, examples=["river-bot-01"])
    results: List[AnalyticsResult] = Field(default_factory=list)


class AnalyticsHistoryPoint(BaseModel):
    """A single historical, recomputed value for one derived parameter.

    Attributes:
        timestamp: The anchor sensor reading's timestamp this point
            was computed from.
        value: The computed value at this point, or ``None`` if not
            computable at that point.
        status: The calculation outcome at this point.
        warnings: Non-fatal warnings raised during this point's
            calculation.
    """

    timestamp: datetime
    value: Optional[float] = None
    status: AnalyticsStatus
    warnings: List[str] = Field(default_factory=list)


class AnalyticsHistoryData(BaseModel):
    """Payload for ``GET /history/analytics/{parameter}``.

    Attributes:
        parameter: The calculator's registry key.
        display_name: Human friendly parameter name.
        unit: Unit of each point's ``value``.
        anchor_sensor: The sensor whose historical readings drove
            this series (see the router's module docstring for the
            anchor-sensor approximation this endpoint uses).
        start: Start of the requested time range.
        end: End of the requested time range.
        page: 1-indexed page number returned.
        page_size: Maximum records requested per page.
        total: Total number of matching anchor-sensor readings across
            all pages.
        total_pages: Total number of pages available.
        points: The recomputed historical series for this page.
    """

    parameter: str = Field(..., examples=["tds"])
    display_name: str = Field(..., examples=["Total Dissolved Solids"])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    anchor_sensor: str = Field(..., examples=["conductivity"])
    start: datetime
    end: datetime
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=1)
    points: List[AnalyticsHistoryPoint] = Field(default_factory=list)
