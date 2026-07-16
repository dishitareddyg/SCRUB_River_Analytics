"""Latest derived-analytics endpoints (``/analytics``).

Serves the Analytics Engine's own output for every registered derived
parameter. Every calculation is performed by
:class:`app.analytics.analytics_engine.AnalyticsEngine` - this module
only shapes its results into the API response and never computes a
value itself.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.calculator_registry import get_calculator
from app.api.dependencies import get_analytics_engine_dependency
from app.api.responses import AnalyticsLatestResponse, success
from app.api.schemas.analytics import AnalyticsLatestData, AnalyticsResult

router = APIRouter(tags=["Analytics"])


@router.get(
    "/latest",
    response_model=AnalyticsLatestResponse,
    summary="Latest derived analytics",
    description=(
        "Returns every registered derived parameter (TDS, salinity, "
        "oxygen saturation/deficit, water density, channel geometry, "
        "flow velocity, river discharge, sediment load, ...) computed "
        "from the latest validated sensor readings via the Analytics "
        "Engine. A parameter reports status 'NOT_COMPUTABLE' (with "
        "its missing inputs listed) rather than being omitted, when "
        "required sensor data or site configuration is unavailable."
    ),
)
def get_latest_analytics(
    device_name: Optional[str] = Query(
        None,
        description="Restrict inputs to a single device. Omit to use the latest readings across all devices.",
        examples=["river-bot-01"],
    ),
    engine: AnalyticsEngine = Depends(get_analytics_engine_dependency),
) -> AnalyticsLatestResponse:
    """Compute and return every registered derived parameter.

    Args:
        device_name: Optional device filter.
        engine: Injected :class:`AnalyticsEngine`.

    Returns:
        An :class:`~app.api.responses.AnalyticsLatestResponse`.
    """
    raw_results = engine.compute_all(device_name=device_name)

    results = [
        AnalyticsResult(
            parameter=key,
            display_name=get_calculator(key).metadata().display_name,
            status=result.status.value,
            value=result.value,
            unit=result.unit,
            timestamp=result.timestamp,
            confidence=result.confidence,
            formula_used=result.formula_used,
            reference=result.reference,
            missing_inputs=result.missing_inputs,
            warnings=result.warnings,
            error_message=result.error_message,
        )
        for key, result in sorted(raw_results.items())
    ]

    data = AnalyticsLatestData(device_name=device_name, results=results)
    return success(data, f"Computed {len(results)} derived parameter(s).")
