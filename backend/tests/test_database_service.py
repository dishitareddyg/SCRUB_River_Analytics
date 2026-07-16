"""Tests for :mod:`app.database.service`.

Exercises :class:`DatabaseService` end-to-end against an in-memory
SQLite database (via an injected ``session_scope_factory``), including
the primary Module 2 integration path: converting a validated
:class:`~app.serial.sensor_packet.SensorPacket` into stored
``sensor_readings`` rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.crud import SystemEventRepository
from app.database.service import DatabaseService
from app.serial.packet_parser import PacketParser
from app.serial.packet_validator import PacketValidator
from tests.database_test_helpers import build_test_session_factory, session_scope_factory_for
from tests.serial_test_helpers import build_test_registry


@pytest.fixture
def db_service(tmp_path) -> DatabaseService:
    """Provide a DatabaseService backed by a fresh in-memory SQLite database."""
    factory = build_test_session_factory()
    return DatabaseService(session_scope_factory=session_scope_factory_for(factory))


def test_register_and_get_device(db_service: DatabaseService) -> None:
    """register_device() then get_device() should round-trip."""
    db_service.register_device("river-bot-01", firmware_version="1.0.0")
    device = db_service.get_device("river-bot-01")

    assert device is not None
    assert device.firmware_version == "1.0.0"


def test_register_device_is_idempotent(db_service: DatabaseService) -> None:
    """Calling register_device() twice should update, not duplicate."""
    first = db_service.register_device("river-bot-01", firmware_version="1.0.0")
    second = db_service.register_device("river-bot-01", firmware_version="1.1.0")

    assert first.id == second.id
    assert second.firmware_version == "1.1.0"


def test_register_sensor(db_service: DatabaseService) -> None:
    """register_sensor() should create a sensor record."""
    sensor = db_service.register_sensor(
        sensor_key="dissolved_oxygen",
        display_name="Dissolved Oxygen",
        unit="mg/L",
        minimum_value=0.0,
        maximum_value=20.0,
    )
    assert sensor.sensor_key == "dissolved_oxygen"


def test_sync_sensor_registry_registers_all_sensors(db_service: DatabaseService, tmp_path) -> None:
    """sync_sensor_registry() should register every sensor from a SensorRegistry."""
    registry = build_test_registry(tmp_path)
    synced = db_service.sync_sensor_registry(registry)

    assert {s.sensor_key for s in synced} == {
        "dissolved_oxygen",
        "ph_level",
        "water_temperature",
        "turbidity",
    }


def test_save_sensor_reading_requires_registered_device_and_sensor(
    db_service: DatabaseService,
) -> None:
    """save_sensor_reading() should return None if device/sensor are unknown."""
    result = db_service.save_sensor_reading(
        device_name="unknown-device",
        sensor_key="unknown-sensor",
        timestamp=datetime.now(timezone.utc),
        value=1.0,
    )
    assert result is None


def test_save_sensor_reading_succeeds_when_registered(db_service: DatabaseService) -> None:
    """save_sensor_reading() should store a reading once device/sensor exist."""
    db_service.register_device("river-bot-01")
    db_service.register_sensor("ph_level", "pH Level")

    reading = db_service.save_sensor_reading(
        device_name="river-bot-01",
        sensor_key="ph_level",
        timestamp=datetime.now(timezone.utc),
        value=7.1,
    )
    assert reading is not None
    assert reading.value == 7.1


def test_get_latest_readings_empty_when_no_data(db_service: DatabaseService) -> None:
    """get_latest_readings() should return an empty list, not raise, when empty."""
    assert db_service.get_latest_readings(device_name="nonexistent") == []


def test_get_latest_readings_returns_most_recent_first(db_service: DatabaseService, tmp_path) -> None:
    """get_latest_readings() should return the N most recent readings."""
    db_service.register_device("river-bot-01")
    db_service.register_sensor("ph_level", "pH Level")

    base = datetime.now(timezone.utc)
    for i in range(3):
        db_service.save_sensor_reading(
            device_name="river-bot-01",
            sensor_key="ph_level",
            timestamp=base + timedelta(seconds=i),
            value=float(i),
        )

    latest = db_service.get_latest_readings(device_name="river-bot-01", sensor_key="ph_level", limit=2)
    assert [r.value for r in latest] == [2.0, 1.0]


def test_get_sensor_history_returns_page(db_service: DatabaseService) -> None:
    """get_sensor_history() should return a Page filtered by time range."""
    db_service.register_device("river-bot-01")
    db_service.register_sensor("ph_level", "pH Level")

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(5):
        db_service.save_sensor_reading(
            device_name="river-bot-01",
            sensor_key="ph_level",
            timestamp=base + timedelta(hours=i),
            value=float(i),
        )

    page = db_service.get_sensor_history(
        sensor_key="ph_level",
        start=base,
        end=base + timedelta(hours=10),
        device_name="river-bot-01",
        page=1,
        page_size=10,
    )
    assert page.total == 5
    assert len(page.items) == 5


def test_get_sensor_history_unknown_sensor_returns_empty_page(db_service: DatabaseService) -> None:
    """get_sensor_history() for an unregistered sensor should return an empty page."""
    page = db_service.get_sensor_history(
        sensor_key="nonexistent",
        start=datetime.now(timezone.utc) - timedelta(days=1),
        end=datetime.now(timezone.utc),
    )
    assert page.total == 0
    assert page.items == []


# ----------------------------------------------------------------------
# save_sensor_packet() — full Module 2 integration path
# ----------------------------------------------------------------------


@pytest.fixture
def registered_service(db_service: DatabaseService, tmp_path):
    """A DatabaseService with the test sensor registry already synced.

    Returns:
        A tuple of ``(db_service, registry)``.
    """
    registry = build_test_registry(tmp_path)
    db_service.sync_sensor_registry(registry)
    return db_service, registry


def _build_validated_packet(registry, sequence: int = 1):
    """Parse and validate a realistic packet using Module 2's own components.

    Args:
        registry: The SensorRegistry to validate against.
        sequence: Packet sequence number to embed.

    Returns:
        A validated :class:`SensorPacket`.
    """
    import json

    line = json.dumps(
        {
            "timestamp": "2026-07-12T09:30:00Z",
            "device_id": "river-bot-01",
            "sequence": sequence,
            "sensors": {"do": 6.72, "ph": 7.24, "water_temperature": 28.4, "mystery_field": 42},
        }
    )
    packet = PacketParser().parse(line)
    PacketValidator(registry).validate(packet)
    return packet


def test_save_sensor_packet_stores_known_readings(registered_service) -> None:
    """save_sensor_packet() should store one row per resolvable sensor reading."""
    db_service, registry = registered_service
    packet = _build_validated_packet(registry)

    stored_count = db_service.save_sensor_packet(packet)

    # do -> dissolved_oxygen, ph -> ph_level, water_temperature -> water_temperature = 3 known;
    # mystery_field is unknown and should be dropped (but not fail the packet).
    assert stored_count == 3

    latest_do = db_service.get_latest_readings(
        device_name="river-bot-01", sensor_key="dissolved_oxygen", limit=1
    )
    assert len(latest_do) == 1
    assert latest_do[0].value == 6.72


def test_save_sensor_packet_registers_device_automatically(registered_service) -> None:
    """save_sensor_packet() should auto-register the device if unseen before."""
    db_service, registry = registered_service
    assert db_service.get_device("river-bot-01") is None

    packet = _build_validated_packet(registry)
    db_service.save_sensor_packet(packet)

    device = db_service.get_device("river-bot-01")
    assert device is not None
    assert device.last_seen_at is not None


def test_save_sensor_packet_logs_system_event_for_unknown_sensor(registered_service) -> None:
    """An unresolved sensor field should produce a system_events row, not fail the packet."""
    db_service, registry = registered_service
    packet = _build_validated_packet(registry)

    db_service.save_sensor_packet(packet)

    with db_service._session_scope() as session:  # test-only introspection
        events = SystemEventRepository(session).list_recent(event_type="unknown_sensor_reading")
        assert len(events) == 1
        assert "mystery_field" in events[0].message


def test_save_sensor_packet_without_device_id_raises() -> None:
    """A packet with no device_id cannot be attributed to a device and must raise."""
    from app.serial.sensor_packet import SensorPacket
    from app.utils.exceptions import DatabaseError

    factory = build_test_session_factory()
    service = DatabaseService(session_scope_factory=session_scope_factory_for(factory))

    packet = SensorPacket(
        device_id=None,
        sequence=1,
        timestamp_raw=None,
        timestamp=None,
        sensors_raw={},
        raw={},
    )
    with pytest.raises(DatabaseError):
        service.save_sensor_packet(packet)


def test_save_sensor_packet_preserves_compound_reading_as_raw_value(tmp_path) -> None:
    """A compound (dict-valued) reading, e.g. GPS, should be stored via raw_value."""
    import json
    import textwrap

    from app.serial.sensor_registry import SensorRegistry

    yaml_path = tmp_path / "gps_sensors.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            sensors:
              - sensor_name: gps_location
                display_name: "GPS"
                description: "Location"
                category: gps
                unit: "deg"
                enabled: true
                sampling_interval: 300
                minimum_value: -180.0
                maximum_value: 180.0
                aliases: ["gps"]
            """
        ),
        encoding="utf-8",
    )
    registry = SensorRegistry(yaml_path=yaml_path)

    factory = build_test_session_factory()
    db_service = DatabaseService(session_scope_factory=session_scope_factory_for(factory))
    db_service.sync_sensor_registry(registry)

    line = json.dumps(
        {
            "timestamp": "2026-07-12T09:30:00Z",
            "device_id": "river-bot-01",
            "sequence": 1,
            "sensors": {"gps": {"latitude": 12.97, "longitude": 77.59}},
        }
    )
    packet = PacketParser().parse(line)
    PacketValidator(registry).validate(packet)

    stored = db_service.save_sensor_packet(packet)
    assert stored == 1

    latest = db_service.get_latest_readings(
        device_name="river-bot-01", sensor_key="gps_location", limit=1
    )
    assert len(latest) == 1
    assert latest[0].value is None
    assert latest[0].raw_value == {"latitude": 12.97, "longitude": 77.59}
