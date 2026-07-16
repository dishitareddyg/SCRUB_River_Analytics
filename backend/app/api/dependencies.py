"""FastAPI dependency-injection providers for the REST API layer.

Every router in :mod:`app.api.routers` obtains its collaborators
(``DatabaseService``, ``AnalyticsEngine``, ``SensorRegistry``,
``Settings``, the serial acquisition status) exclusively through
``Depends(...)`` on the functions in this module, rather than
importing singletons directly. This keeps every route handler trivial
to unit test: a test only needs to override the relevant provider via
``app.dependency_overrides`` (see ``tests/api_test_helpers.py``).

This module does not modify any previous module - it only composes
their existing public singletons/factories
(:func:`app.database.service.get_database_service`,
:func:`app.config.settings.get_settings`,
:func:`app.serial.sensor_registry.get_sensor_registry`,
:func:`app.analytics.config.get_analytics_config`) and constructs the
one new collaborator this layer needs
(:class:`app.analytics.analytics_engine.AnalyticsEngine`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Depends

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.config.settings import Settings, get_settings
from app.database.service import DatabaseService, get_database_service
from app.historical.service import HistoricalAnalyticsService
from app.serial.sensor_registry import SensorRegistry, get_sensor_registry
from app.serial.serial_manager import SerialManager

# Recorded once, at module import time (i.e. when the API process
# starts), so `/system/health` can report a meaningful process
# uptime without requiring any change to app/main.py's lifespan.
_PROCESS_START_TIME: datetime = datetime.now(timezone.utc)


def get_uptime_seconds() -> float:
    """Compute how long this API process has been running.

    Returns:
        Seconds elapsed since this module was first imported (a close
        proxy for process start, since routers/dependencies are
        imported during application construction).
    """
    return (datetime.now(timezone.utc) - _PROCESS_START_TIME).total_seconds()


def get_settings_dependency() -> Settings:
    """Provide the application :class:`Settings`.

    Returns:
        The process-wide cached :class:`Settings` instance.
    """
    return get_settings()


def get_sensor_registry_dependency() -> SensorRegistry:
    """Provide the configured :class:`SensorRegistry`.

    Returns:
        The process-wide cached :class:`SensorRegistry` instance,
        loaded from ``app/config/sensors.yaml``.
    """
    return get_sensor_registry()


def get_analytics_config_dependency() -> AnalyticsConfig:
    """Provide the :class:`AnalyticsConfig`.

    Returns:
        The process-wide cached :class:`AnalyticsConfig` instance,
        loaded from ``app/config/analytics.yaml``.
    """
    return get_analytics_config()


@lru_cache
def _serial_manager_singleton() -> SerialManager:
    """Build (once) the process-wide :class:`SerialManager` used for status reporting.

    Constructing a :class:`SerialManager` does not open the serial
    port or start its background thread - only calling ``.start()``
    does that, and this API layer never calls it (starting serial
    acquisition is Module 2's concern, wired from ``app/main.py``'s
    lifespan if/when a future revision chooses to). Until then, this
    manager's ``.devices``/``.status`` sub-managers simply, and
    correctly, report "no device connected" / "disconnected" - an
    accurate reflection of this process's actual state.

    Returns:
        A constructed-but-never-started :class:`SerialManager`.
    """
    return SerialManager()


def get_serial_manager_dependency() -> SerialManager:
    """Provide the process-wide :class:`SerialManager` (for status only).

    Returns:
        The cached, never-started :class:`SerialManager` singleton.
    """
    return _serial_manager_singleton()


def get_analytics_engine_dependency(
    db: DatabaseService = Depends(get_database_service),
    config: AnalyticsConfig = Depends(get_analytics_config_dependency),
) -> AnalyticsEngine:
    """Provide an :class:`AnalyticsEngine` bound to the current request's collaborators.

    Deliberately *not* cached: construction is cheap (no I/O), and
    building it fresh per-request means overriding
    ``get_database_service`` or ``get_analytics_config_dependency`` in
    tests (via ``app.dependency_overrides``) transparently propagates
    here, without needing a separate override for the engine itself.

    Args:
        db: The database facade, injected.
        config: The Analytics Engine configuration, injected.

    Returns:
        A ready-to-use :class:`AnalyticsEngine`.
    """
    return AnalyticsEngine(database_service=db, config=config)


def get_historical_service_dependency(
    db: DatabaseService = Depends(get_database_service),
    registry: SensorRegistry = Depends(get_sensor_registry_dependency),
    config: AnalyticsConfig = Depends(get_analytics_config_dependency),
) -> HistoricalAnalyticsService:
    """Provide a :class:`HistoricalAnalyticsService` bound to the current request's collaborators.

    Deliberately *not* cached, for the same reason as
    :func:`get_analytics_engine_dependency`: construction is cheap,
    and building it fresh per-request means overriding any of
    ``get_database_service``, ``get_sensor_registry_dependency``, or
    ``get_analytics_config_dependency`` in tests transparently
    propagates here.

    Args:
        db: The database facade, injected.
        registry: The configured sensor registry, injected.
        config: The Analytics Engine configuration, injected.

    Returns:
        A ready-to-use :class:`HistoricalAnalyticsService`.
    """
    return HistoricalAnalyticsService(db=db, sensor_registry=registry, analytics_config=config)
