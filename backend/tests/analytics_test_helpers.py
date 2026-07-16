"""Shared helpers for the Analytics Engine test suite.

Not a pytest ``conftest.py`` on purpose (imported explicitly by the
analytics test modules), mirroring the pattern used by
``tests/database_test_helpers.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from app.analytics.config import AnalyticsConfig, load_analytics_config
from app.database.service import DatabaseService
from tests.database_test_helpers import build_test_session_factory, session_scope_factory_for


def base_analytics_config() -> AnalyticsConfig:
    """Load the real, checked-in ``analytics.yaml`` as a starting point.

    Returns:
        The parsed :class:`AnalyticsConfig` from the project's actual
        configuration file (unconfigured site-survey values remain
        ``None``, matching production defaults).
    """
    return load_analytics_config()


def configured_analytics_config(
    *,
    bed_width_m: float = 5.0,
    side_slope_h_per_v: float = 2.0,
    channel_slope_m_per_m: float = 0.001,
    velocity_equation: str = "manning",
    chezy_coefficient_c: Optional[float] = None,
) -> AnalyticsConfig:
    """Build an :class:`AnalyticsConfig` with site geometry/hydraulics filled in.

    The checked-in ``analytics.yaml`` intentionally leaves
    site-survey values (``bed_width_m``, ``side_slope_h_per_v``,
    ``channel_slope_m_per_m``) as ``None`` so a fresh deployment fails
    safe (``NOT_COMPUTABLE``) rather than guessing a channel shape.
    Tests that exercise the geometry/hydraulic/sediment calculators
    need those values populated, hence this helper.

    Args:
        bed_width_m: Trapezoidal channel bed width, in meters.
        side_slope_h_per_v: Trapezoidal side slope (horizontal per
            unit vertical).
        channel_slope_m_per_m: Longitudinal channel bed slope.
        velocity_equation: ``"manning"`` or ``"chezy"``.
        chezy_coefficient_c: Chezy coefficient, required only when
            ``velocity_equation="chezy"``.

    Returns:
        A populated :class:`AnalyticsConfig`.
    """
    config = base_analytics_config()
    geometry = replace(
        config.geometry, bed_width_m=bed_width_m, side_slope_h_per_v=side_slope_h_per_v
    )
    hydraulic = replace(
        config.hydraulic,
        channel_slope_m_per_m=channel_slope_m_per_m,
        velocity_equation=velocity_equation,
        chezy_coefficient_c=chezy_coefficient_c,
    )
    return replace(config, geometry=geometry, hydraulic=hydraulic)


def build_populated_db_service(
    device_name: str, readings: dict[str, float]
) -> DatabaseService:
    """Build an in-memory-SQLite-backed DatabaseService with seeded readings.

    Registers ``device_name`` and one sensor per key in ``readings``,
    then stores each value as the latest reading for that sensor.

    Args:
        device_name: The device name to register and attribute
            readings to.
        readings: Mapping of sensor_key -> value to seed.

    Returns:
        A ready-to-use :class:`DatabaseService`.
    """
    factory = build_test_session_factory()
    db_service = DatabaseService(session_scope_factory=session_scope_factory_for(factory))
    db_service.register_device(device_name)
    now = datetime.now(timezone.utc)
    for sensor_key, value in readings.items():
        db_service.register_sensor(sensor_key=sensor_key, display_name=sensor_key)
        db_service.save_sensor_reading(
            device_name=device_name,
            sensor_key=sensor_key,
            timestamp=now,
            value=value,
        )
    return db_service
