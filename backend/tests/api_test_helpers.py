"""Shared helpers for the REST API (``app/api``) test suite.

Not a pytest ``conftest.py`` on purpose (imported explicitly by the
API test modules), mirroring the pattern used by
``tests/database_test_helpers.py`` and ``tests/analytics_test_helpers.py``.

Every API test gets its own isolated in-memory SQLite
``DatabaseService`` (never the real, configured PostgreSQL database)
via FastAPI's ``app.dependency_overrides``, so tests never depend on
network access or shared state.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.api.dependencies import get_analytics_config_dependency
from app.database.service import DatabaseService, get_database_service
from app.main import app
from tests.database_test_helpers import build_test_session_factory, session_scope_factory_for


def build_isolated_db_service() -> DatabaseService:
    """Build a fresh, isolated in-memory-SQLite-backed DatabaseService.

    Returns:
        A ready-to-use :class:`DatabaseService` with its own private
        database (nothing shared with other tests or the real app).
    """
    factory = build_test_session_factory()
    return DatabaseService(session_scope_factory=session_scope_factory_for(factory))


def seed_readings(
    db_service: DatabaseService,
    device_name: str,
    readings: Dict[str, float],
    *,
    timestamp: Optional[datetime] = None,
) -> None:
    """Register a device/sensors and store one reading per sensor.

    Args:
        db_service: The target :class:`DatabaseService`.
        device_name: Device name to register and attribute readings to.
        readings: Mapping of sensor_key -> value to seed.
        timestamp: Timestamp to use for every seeded reading. Defaults
            to "now" (UTC).
    """
    db_service.register_device(device_name)
    when = timestamp or datetime.now(timezone.utc)
    for sensor_key, value in readings.items():
        db_service.register_sensor(sensor_key=sensor_key, display_name=sensor_key)
        db_service.save_sensor_reading(
            device_name=device_name, sensor_key=sensor_key, timestamp=when, value=value
        )


def geometry_configured_analytics_config() -> AnalyticsConfig:
    """Build an :class:`AnalyticsConfig` with site geometry/hydraulics filled in.

    Mirrors ``tests/analytics_test_helpers.configured_analytics_config``,
    reimplemented here (rather than imported) to keep the API test
    suite independent of the analytics test suite's internal helpers.

    Returns:
        A populated :class:`AnalyticsConfig` suitable for exercising
        the geometry/hydrology/sediment endpoints end-to-end.
    """
    config = get_analytics_config()
    geometry = replace(config.geometry, bed_width_m=5.0, side_slope_h_per_v=2.0)
    hydraulic = replace(config.hydraulic, channel_slope_m_per_m=0.001, velocity_equation="manning")
    return replace(config, geometry=geometry, hydraulic=hydraulic)


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """Provide a :class:`TestClient` bound to an isolated in-memory database.

    Overrides :func:`app.database.service.get_database_service` for
    the duration of the test and cleans the override up afterward, so
    tests never touch the real (PostgreSQL) database and never leak
    overrides into other test modules.

    Yields:
        A :class:`TestClient` plus, via ``client.db_service``, direct
        access to the underlying isolated :class:`DatabaseService` for
        seeding data.
    """
    db_service = build_isolated_db_service()
    app.dependency_overrides[get_database_service] = lambda: db_service

    with TestClient(app) as client:
        client.db_service = db_service  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.pop(get_database_service, None)


@pytest.fixture
def api_client_with_geometry(api_client: TestClient) -> Iterator[TestClient]:
    """Like :func:`api_client`, with site geometry/hydraulics also configured.

    Args:
        api_client: The base isolated-database client fixture.

    Yields:
        The same :class:`TestClient`, with
        :func:`app.api.dependencies.get_analytics_config_dependency`
        additionally overridden to report a configured channel
        geometry (bed width, side slope, slope), so geometry/
        hydrology/sediment endpoints can be exercised in their OK
        path.
    """
    configured = geometry_configured_analytics_config()
    app.dependency_overrides[get_analytics_config_dependency] = lambda: configured
    yield api_client
    app.dependency_overrides.pop(get_analytics_config_dependency, None)
