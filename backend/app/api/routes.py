"""Top-level API router assembly.

This module defines the versioned ``/api/v1`` router and the single
foundational endpoint (``/health``) provided by this backend
foundation module. Future modules will create their own
``APIRouter`` instances (e.g. in ``live.py``, ``analytics.py``,
``trends.py``, ``prediction.py``, ``reports.py``) and ``include_router``
them here - the rest of the application (``main.py``) only ever
imports this single ``api_router``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import analytics as analytics_router_module
from app.api.routers import historical as historical_router_module
from app.api.routers import history as history_router_module
from app.api.routers import live as live_router_module
from app.api.routers import system as system_router_module
from app.config.settings import get_settings
from app.database.db import check_database_connection
from app.utils.response import HealthComponent, HealthResponse

health_router = APIRouter(tags=["Health"])


@health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description=(
        "Reports the overall health of the backend, including "
        "connectivity to the database. Used by monitoring tools and "
        "the dashboard's Arduino/database status indicators."
    ),
)
def health_check() -> HealthResponse:
    """Report backend and database health.

    Returns:
        A :class:`HealthResponse` describing overall and per-component
        health. The endpoint always returns HTTP 200; clients should
        inspect the ``status``/``success`` fields to determine actual
        health, since a hard failure here would defeat the purpose of
        a health check.
    """
    settings = get_settings()

    database_ok = check_database_connection()

    components = [
        HealthComponent(
            name="database",
            status="ok" if database_ok else "degraded",
            detail=None if database_ok else "Database is unreachable.",
        ),
    ]

    overall_ok = all(component.status == "ok" for component in components)

    return HealthResponse(
        success=overall_ok,
        status="ok" if overall_ok else "degraded",
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.environment,
        components=components,
    )


# ---------------------------------------------------------------------------
# Versioned API router.
#
# Future modules append their routers here, e.g.:
#
#     from app.api.live import router as live_router
#     api_router.include_router(live_router, prefix="/live", tags=["Live"])
#
# ---------------------------------------------------------------------------
api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(system_router_module.router, prefix="/system")
api_router.include_router(live_router_module.router, prefix="/live")
api_router.include_router(analytics_router_module.router, prefix="/analytics")
api_router.include_router(history_router_module.router, prefix="/history")
api_router.include_router(historical_router_module.router, prefix="/history")
