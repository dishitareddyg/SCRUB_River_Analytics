"""Tests for :mod:`app.database.retention`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.database.crud import DeviceRepository, SensorReadingRepository, SensorRepository
from app.database.retention import RetentionManager
from tests.database_test_helpers import build_test_session_factory


@pytest.fixture
def session() -> Session:
    """Provide a fresh, isolated in-memory SQLite session per test."""
    factory = build_test_session_factory()
    with factory() as db_session:
        yield db_session


def _seed_readings(session: Session, days: int = 10):
    """Seed one reading per day for ``days`` days starting from a fixed base.

    Args:
        session: The active test session.
        days: Number of days of readings to seed.

    Returns:
        The base (oldest) timestamp used.
    """
    device = DeviceRepository(session).create(device_name="river-bot-01")
    sensor = SensorRepository(session).upsert_by_key("ph_level", "pH Level")
    session.commit()

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repo = SensorReadingRepository(session)
    for i in range(days):
        repo.create(
            device_id=device.id,
            sensor_id=sensor.id,
            timestamp=base + timedelta(days=i),
            value=float(i),
        )
    session.commit()
    return base


def test_count_older_than(session: Session) -> None:
    """count_older_than() should count readings before the cutoff."""
    base = _seed_readings(session, days=10)
    manager = RetentionManager(session)

    cutoff = base + timedelta(days=5)
    assert manager.count_older_than(cutoff) == 5


def test_archive_to_csv_writes_expected_rows(session: Session, tmp_path) -> None:
    """archive_to_csv() should write one row per matching reading and not delete anything."""
    base = _seed_readings(session, days=10)
    manager = RetentionManager(session)

    cutoff = base + timedelta(days=5)
    output_path = tmp_path / "archive.csv"
    result = manager.archive_to_csv(cutoff, output_path)

    assert result.row_count == 5
    assert output_path.exists()

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 5  # header + 5 data rows

    # Archiving must be non-destructive.
    assert manager.count_older_than(base + timedelta(days=100)) == 10


def test_purge_older_than_deletes_matching_rows(session: Session) -> None:
    """purge_older_than() should permanently delete readings before the cutoff."""
    base = _seed_readings(session, days=10)
    manager = RetentionManager(session)

    cutoff = base + timedelta(days=3)
    deleted = manager.purge_older_than(cutoff)
    session.commit()

    assert deleted == 3
    assert manager.count_older_than(base + timedelta(days=100)) == 7


def test_retention_manager_exposes_only_opt_in_methods() -> None:
    """Sanity check: nothing in this module schedules or auto-invokes purge/archive."""
    import app.database.retention as retention_module

    assert not hasattr(retention_module, "start")
    assert not hasattr(retention_module, "scheduler")
