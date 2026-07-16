"""Tests for :mod:`app.database.models` and basic connection behavior."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.db import check_database_connection
from app.database.models import Device, Sensor, SensorReading
from tests.database_test_helpers import build_test_session_factory


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Provide a fresh in-memory SQLite session factory per test."""
    return build_test_session_factory()


def test_check_database_connection_returns_false_without_a_live_database() -> None:
    """With no reachable Postgres instance configured in this sandbox,
    check_database_connection() should degrade gracefully to False
    rather than raising."""
    assert check_database_connection() is False


def test_device_can_be_created_and_retrieved(session_factory: sessionmaker[Session]) -> None:
    """A Device row should round-trip through the ORM correctly."""
    with session_factory() as session:
        device = Device(device_name="river-bot-01", firmware_version="1.0.0")
        session.add(device)
        session.commit()

        fetched = session.query(Device).filter_by(device_name="river-bot-01").one()
        assert fetched.id == device.id
        assert isinstance(fetched.id, uuid.UUID)
        assert fetched.firmware_version == "1.0.0"
        assert fetched.connection_status == "unknown"


def test_device_name_must_be_unique(session_factory: sessionmaker[Session]) -> None:
    """Inserting two devices with the same name should violate the
    unique constraint."""
    with session_factory() as session:
        session.add(Device(device_name="dup-device"))
        session.commit()

        session.add(Device(device_name="dup-device"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_sensor_can_be_created_and_retrieved(session_factory: sessionmaker[Session]) -> None:
    """A Sensor row should round-trip through the ORM correctly."""
    with session_factory() as session:
        sensor = Sensor(
            sensor_key="dissolved_oxygen",
            display_name="Dissolved Oxygen",
            unit="mg/L",
            minimum_value=0.0,
            maximum_value=20.0,
            enabled=True,
        )
        session.add(sensor)
        session.commit()

        fetched = session.query(Sensor).filter_by(sensor_key="dissolved_oxygen").one()
        assert fetched.display_name == "Dissolved Oxygen"
        assert fetched.enabled is True


def test_sensor_reading_links_to_device_and_sensor(session_factory: sessionmaker[Session]) -> None:
    """A SensorReading should correctly reference its parent Device/Sensor
    by foreign key, and be queryable via both relationships."""
    with session_factory() as session:
        device = Device(device_name="river-bot-01")
        sensor = Sensor(sensor_key="ph_level", display_name="pH Level", unit="pH")
        session.add_all([device, sensor])
        session.flush()

        reading = SensorReading(
            device_id=device.id,
            sensor_id=sensor.id,
            timestamp=datetime.now(timezone.utc),
            value=7.2,
            validation_status="valid",
        )
        session.add(reading)
        session.commit()

        device_id, sensor_id = device.id, sensor.id

        readings_for_device = session.query(SensorReading).filter_by(device_id=device_id).all()
        readings_for_sensor = session.query(SensorReading).filter_by(sensor_id=sensor_id).all()

        assert len(readings_for_device) == 1
        assert readings_for_device[0].value == 7.2
        assert len(readings_for_sensor) == 1
        assert readings_for_sensor[0].value == 7.2


def test_sensor_reading_supports_compound_raw_value(session_factory: sessionmaker[Session]) -> None:
    """raw_value should persist arbitrary JSON-compatible payloads (e.g. GPS)."""
    with session_factory() as session:
        device = Device(device_name="river-bot-01")
        sensor = Sensor(sensor_key="gps_location", display_name="GPS")
        session.add_all([device, sensor])
        session.flush()

        reading = SensorReading(
            device_id=device.id,
            sensor_id=sensor.id,
            timestamp=datetime.now(timezone.utc),
            value=None,
            raw_value={"latitude": 12.97, "longitude": 77.59},
            validation_status="valid",
        )
        session.add(reading)
        session.commit()

        session.expire_all()
        fetched = session.get(SensorReading, (reading.id, reading.timestamp))
        assert fetched.raw_value == {"latitude": 12.97, "longitude": 77.59}


def test_device_delete_cascades_to_readings(session_factory: sessionmaker[Session]) -> None:
    """Deleting a Device should cascade-delete its SensorReading rows."""
    with session_factory() as session:
        device = Device(device_name="river-bot-01")
        sensor = Sensor(sensor_key="ph_level", display_name="pH Level")
        session.add_all([device, sensor])
        session.flush()

        session.add(
            SensorReading(
                device_id=device.id,
                sensor_id=sensor.id,
                timestamp=datetime.now(timezone.utc),
                value=7.0,
            )
        )
        session.commit()

        session.delete(device)
        session.commit()

        assert session.query(SensorReading).count() == 0
