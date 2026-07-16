"""Tests for :mod:`app.database.crud` repository classes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.database.crud import (
    DeviceRepository,
    SensorReadingRepository,
    SensorRepository,
    SystemEventRepository,
)
from tests.database_test_helpers import build_test_session_factory


@pytest.fixture
def session() -> Session:
    """Provide a fresh, isolated in-memory SQLite session per test."""
    factory = build_test_session_factory()
    with factory() as db_session:
        yield db_session


# ----------------------------------------------------------------------
# DeviceRepository
# ----------------------------------------------------------------------


def test_device_repository_create_and_get_by_name(session: Session) -> None:
    """create() then get_by_name() should round-trip a device."""
    repo = DeviceRepository(session)
    repo.create(device_name="river-bot-01", firmware_version="1.0.0")
    session.commit()

    fetched = repo.get_by_name("river-bot-01")
    assert fetched is not None
    assert fetched.firmware_version == "1.0.0"


def test_device_repository_get_by_name_missing_returns_none(session: Session) -> None:
    """get_by_name() should return None, not raise, when absent."""
    repo = DeviceRepository(session)
    assert repo.get_by_name("does-not-exist") is None


def test_device_repository_upsert_creates_then_updates(session: Session) -> None:
    """upsert_by_name() should create on first call and update on second."""
    repo = DeviceRepository(session)

    created = repo.upsert_by_name("river-bot-01", firmware_version="1.0.0")
    session.commit()
    assert created.firmware_version == "1.0.0"

    updated = repo.upsert_by_name("river-bot-01", firmware_version="2.0.0")
    session.commit()
    assert updated.id == created.id
    assert updated.firmware_version == "2.0.0"

    assert session.query(type(created)).count() == 1


def test_device_repository_list_all_paginates(session: Session) -> None:
    """list_all() should paginate devices ordered by name."""
    repo = DeviceRepository(session)
    for i in range(5):
        repo.create(device_name=f"device-{i}")
    session.commit()

    page = repo.list_all(page=1, page_size=2)
    assert page.total == 5
    assert len(page.items) == 2
    assert page.total_pages == 3


def test_device_repository_update_status(session: Session) -> None:
    """update_status() should change connection_status on an existing device."""
    repo = DeviceRepository(session)
    device = repo.create(device_name="river-bot-01")
    session.commit()

    updated = repo.update_status(device.id, "connected")
    assert updated is not None
    assert updated.connection_status == "connected"


def test_device_repository_delete(session: Session) -> None:
    """delete() should remove the device and report success."""
    repo = DeviceRepository(session)
    device = repo.create(device_name="river-bot-01")
    session.commit()

    assert repo.delete(device.id) is True
    assert repo.get_by_id(device.id) is None
    assert repo.delete(device.id) is False


# ----------------------------------------------------------------------
# SensorRepository
# ----------------------------------------------------------------------


def test_sensor_repository_upsert_and_list_enabled(session: Session) -> None:
    """upsert_by_key() should create/update, and list_enabled() should filter."""
    repo = SensorRepository(session)
    repo.upsert_by_key("dissolved_oxygen", "Dissolved Oxygen", enabled=True)
    repo.upsert_by_key("turbidity", "Turbidity", enabled=False)
    session.commit()

    enabled = repo.list_enabled()
    keys = {sensor.sensor_key for sensor in enabled}
    assert keys == {"dissolved_oxygen"}


def test_sensor_repository_upsert_updates_existing_fields(session: Session) -> None:
    """Re-upserting the same sensor_key should update, not duplicate."""
    repo = SensorRepository(session)
    repo.upsert_by_key("ph_level", "pH", unit="pH", minimum_value=0.0, maximum_value=14.0)
    session.commit()

    repo.upsert_by_key("ph_level", "pH Level", unit="pH", minimum_value=0.0, maximum_value=14.0)
    session.commit()

    assert session.query(type(repo.get_by_key("ph_level"))).count() == 1
    assert repo.get_by_key("ph_level").display_name == "pH Level"


# ----------------------------------------------------------------------
# SensorReadingRepository
# ----------------------------------------------------------------------


def _seed_device_and_sensor(session: Session):
    """Create a device and sensor for reading tests.

    Args:
        session: The active test session.

    Returns:
        A tuple of ``(device, sensor)``.
    """
    device = DeviceRepository(session).create(device_name="river-bot-01")
    sensor = SensorRepository(session).upsert_by_key("dissolved_oxygen", "Dissolved Oxygen")
    session.commit()
    return device, sensor


def test_sensor_reading_repository_create(session: Session) -> None:
    """create() should insert a single reading."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    reading = repo.create(
        device_id=device.id,
        sensor_id=sensor.id,
        timestamp=datetime.now(timezone.utc),
        value=6.5,
    )
    session.commit()

    assert reading.value == 6.5


def test_sensor_reading_repository_bulk_create(session: Session) -> None:
    """bulk_create() should insert multiple readings in one call."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)
    from app.database.models import SensorReading

    now = datetime.now(timezone.utc)
    readings = [
        SensorReading(device_id=device.id, sensor_id=sensor.id, timestamp=now, value=float(i))
        for i in range(3)
    ]
    repo.bulk_create(readings)
    session.commit()

    assert session.query(SensorReading).count() == 3


def test_sensor_reading_repository_get_latest(session: Session) -> None:
    """get_latest() should return the most recent reading for a pair."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    base = datetime.now(timezone.utc)
    repo.create(device_id=device.id, sensor_id=sensor.id, timestamp=base, value=1.0)
    repo.create(
        device_id=device.id, sensor_id=sensor.id, timestamp=base + timedelta(seconds=5), value=2.0
    )
    session.commit()

    latest = repo.get_latest(device.id, sensor.id)
    assert latest is not None
    assert latest.value == 2.0


def test_sensor_reading_repository_get_latest_n(session: Session) -> None:
    """get_latest_n() should return the N most recent readings, newest first."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    base = datetime.now(timezone.utc)
    for i in range(5):
        repo.create(
            device_id=device.id,
            sensor_id=sensor.id,
            timestamp=base + timedelta(seconds=i),
            value=float(i),
        )
    session.commit()

    latest_three = repo.get_latest_n(3, device_id=device.id, sensor_id=sensor.id)
    assert [r.value for r in latest_three] == [4.0, 3.0, 2.0]


def test_sensor_reading_repository_get_history_time_range_and_pagination(session: Session) -> None:
    """get_history() should filter by time range and paginate chronologically."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(10):
        repo.create(
            device_id=device.id,
            sensor_id=sensor.id,
            timestamp=base + timedelta(hours=i),
            value=float(i),
        )
    session.commit()

    start = base + timedelta(hours=2)
    end = base + timedelta(hours=6)
    page = repo.get_history(start=start, end=end, device_id=device.id, page=1, page_size=3)

    assert page.total == 5  # hours 2,3,4,5,6 inclusive
    assert len(page.items) == 3
    assert [r.value for r in page.items] == [2.0, 3.0, 4.0]

    page2 = repo.get_history(start=start, end=end, device_id=device.id, page=2, page_size=3)
    assert [r.value for r in page2.items] == [5.0, 6.0]


def test_sensor_reading_repository_count_in_range(session: Session) -> None:
    """count_in_range() should count without needing to fetch rows."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(4):
        repo.create(
            device_id=device.id, sensor_id=sensor.id, timestamp=base + timedelta(hours=i), value=1.0
        )
    session.commit()

    count = repo.count_in_range(base, base + timedelta(hours=10))
    assert count == 4


def test_sensor_reading_repository_delete_older_than(session: Session) -> None:
    """delete_older_than() should remove only readings before the cutoff."""
    device, sensor = _seed_device_and_sensor(session)
    repo = SensorReadingRepository(session)

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(5):
        repo.create(
            device_id=device.id, sensor_id=sensor.id, timestamp=base + timedelta(days=i), value=1.0
        )
    session.commit()

    cutoff = base + timedelta(days=2)
    deleted = repo.delete_older_than(cutoff)
    session.commit()

    assert deleted == 2
    remaining = repo.count_in_range(base, base + timedelta(days=10))
    assert remaining == 3


# ----------------------------------------------------------------------
# SystemEventRepository
# ----------------------------------------------------------------------


def test_system_event_repository_create_and_list_recent(session: Session) -> None:
    """create() then list_recent() should return events, most recent first."""
    repo = SystemEventRepository(session)
    repo.create(event_type="device_connected", message="Device connected", severity="info")
    repo.create(event_type="device_disconnected", message="Device disconnected", severity="warning")
    session.commit()

    recent = repo.list_recent(limit=10)
    assert len(recent) == 2
    assert recent[0].event_type == "device_disconnected"  # most recent first


def test_system_event_repository_filters_by_type_and_severity(session: Session) -> None:
    """list_recent() should support filtering by event_type/severity."""
    repo = SystemEventRepository(session)
    repo.create(event_type="reconnect", message="reconnected", severity="warning")
    repo.create(event_type="reconnect", message="reconnected again", severity="warning")
    repo.create(event_type="startup", message="started", severity="info")
    session.commit()

    reconnects = repo.list_recent(event_type="reconnect")
    assert len(reconnects) == 2

    info_events = repo.list_recent(severity="info")
    assert len(info_events) == 1
