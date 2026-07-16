"""Shared helpers for the historical analytics (``app/historical``) test suite.

Not a pytest ``conftest.py`` on purpose, mirroring the pattern used by
``tests/database_test_helpers.py`` and ``tests/analytics_test_helpers.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence

from app.database.service import DatabaseService
from tests.database_test_helpers import build_test_session_factory, session_scope_factory_for


def build_isolated_db_service() -> DatabaseService:
    """Build a fresh, isolated in-memory-SQLite-backed DatabaseService.

    Returns:
        A ready-to-use :class:`DatabaseService` with its own private
        database.
    """
    factory = build_test_session_factory()
    return DatabaseService(session_scope_factory=session_scope_factory_for(factory))


def seed_time_series(
    db: DatabaseService,
    device_name: str,
    sensor_key: str,
    values: Sequence[float],
    *,
    start: Optional[datetime] = None,
    step: timedelta = timedelta(hours=1),
    unit: Optional[str] = None,
    value_fn: Optional[Callable[[int, float], Optional[float]]] = None,
) -> datetime:
    """Register a device/sensor and store one evenly-spaced reading per value.

    Args:
        db: The target :class:`DatabaseService`.
        device_name: Device name to register and attribute readings to.
        sensor_key: Sensor key to register and store readings under.
        values: The sequence of values to store, oldest first.
        start: Timestamp of the first reading. Defaults to
            ``len(values) * step`` before "now".
        step: Time spacing between consecutive readings.
        unit: Optional unit of measurement to register the sensor with.
        value_fn: Optional ``(index, value) -> value_or_None``
            transform applied before storage (e.g. to inject missing
            values).

    Returns:
        The timestamp used for the first (oldest) reading.
    """
    db.register_device(device_name)
    db.register_sensor(sensor_key=sensor_key, display_name=sensor_key, unit=unit)

    base = start or (datetime.now(timezone.utc) - step * len(values))
    for index, value in enumerate(values):
        stored_value = value_fn(index, value) if value_fn else value
        db.save_sensor_reading(
            device_name=device_name,
            sensor_key=sensor_key,
            timestamp=base + step * index,
            value=stored_value,
        )
    return base
