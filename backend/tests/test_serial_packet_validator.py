"""Unit tests for :mod:`app.serial.packet_validator`."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.serial.packet_validator import PacketValidator
from app.serial.sensor_packet import SensorPacket
from tests.serial_test_helpers import build_test_registry


@pytest.fixture
def registry(tmp_path: Path):
    """Provide a deterministic sensor registry for validator tests."""
    return build_test_registry(tmp_path)


def _make_packet(**overrides: object) -> SensorPacket:
    """Build a valid baseline SensorPacket, allowing field overrides.

    Args:
        **overrides: Fields to override on the constructed packet.

    Returns:
        A :class:`SensorPacket` instance.
    """
    defaults = dict(
        device_id="river-bot-01",
        sequence=1,
        timestamp_raw="2026-07-12T09:30:00Z",
        timestamp=datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc),
        sensors_raw={"do": 6.5, "ph": 7.1},
        raw={},
    )
    defaults.update(overrides)
    return SensorPacket(**defaults)  # type: ignore[arg-type]


def test_valid_packet_passes_validation(registry) -> None:
    """A well-formed packet with in-range known sensors should be valid."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet())

    assert result.is_valid
    assert result.errors == []
    reading = _make_packet()
    validator.validate(reading)


def test_missing_device_id_is_fatal(registry) -> None:
    """A packet without a device_id must fail validation."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet(device_id=None))

    assert not result.is_valid
    assert any("device_id" in error for error in result.errors)


def test_missing_sequence_is_fatal(registry) -> None:
    """A packet without a sequence number must fail validation."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet(sequence=None))

    assert not result.is_valid
    assert any("sequence" in error for error in result.errors)


def test_unparseable_timestamp_is_fatal(registry) -> None:
    """A packet whose timestamp failed to parse must fail validation."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet(timestamp_raw="bad", timestamp=None))

    assert not result.is_valid
    assert any("timestamp" in error.lower() for error in result.errors)


def test_empty_sensors_is_fatal(registry) -> None:
    """A packet with no sensor readings at all must fail validation."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet(sensors_raw={}))

    assert not result.is_valid


def test_unknown_sensor_field_is_a_warning_not_fatal(registry) -> None:
    """An unrecognized sensor field should warn but not fail the packet."""
    validator = PacketValidator(registry)
    result = validator.validate(_make_packet(sensors_raw={"do": 6.5, "mystery_field": 1}))

    assert result.is_valid
    assert any("mystery_field" in warning for warning in result.warnings)


def test_out_of_range_value_is_flagged_on_the_reading(registry) -> None:
    """An out-of-range known sensor value should be marked invalid, but the
    overall packet remains valid (range issues are per-reading, not fatal)."""
    validator = PacketValidator(registry)
    packet = _make_packet(sensors_raw={"do": 999.0})
    result = validator.validate(packet)

    assert result.is_valid
    reading = packet.get_reading("dissolved_oxygen")
    assert reading is not None
    assert not reading.is_valid
    assert "range" in (reading.error or "").lower()


def test_non_numeric_value_for_known_sensor_is_flagged(registry) -> None:
    """A non-numeric value for a known scalar sensor should be flagged invalid."""
    validator = PacketValidator(registry)
    packet = _make_packet(sensors_raw={"do": "not-a-number"})
    validator.validate(packet)

    reading = packet.get_reading("dissolved_oxygen")
    assert reading is not None
    assert not reading.is_valid


def test_disabled_sensor_is_flagged_invalid(registry) -> None:
    """A recognized-but-disabled sensor field should be flagged invalid."""
    validator = PacketValidator(registry)
    packet = _make_packet(sensors_raw={"turbidity": 15.0})
    validator.validate(packet)

    reading = packet.get_reading("turbidity")
    assert reading is not None
    assert not reading.is_valid
    assert "disabled" in (reading.error or "").lower()


def test_duplicate_sequence_is_a_warning(registry) -> None:
    """Sending the same (device_id, sequence) twice should warn on the second."""
    validator = PacketValidator(registry)
    first = validator.validate(_make_packet(sequence=5))
    second = validator.validate(_make_packet(sequence=5))

    assert first.is_valid
    assert second.is_valid
    assert any("duplicate" in warning.lower() for warning in second.warnings)


def test_out_of_order_sequence_is_a_warning(registry) -> None:
    """A sequence number lower than the last seen one should warn."""
    validator = PacketValidator(registry)
    validator.validate(_make_packet(sequence=10))
    result = validator.validate(_make_packet(sequence=3))

    assert result.is_valid
    assert any("out-of-order" in warning.lower() for warning in result.warnings)


def test_missing_enabled_sensors_reports_absent_channels(registry) -> None:
    """missing_enabled_sensors should list enabled sensors absent from a packet."""
    validator = PacketValidator(registry)
    packet = _make_packet(sensors_raw={"do": 6.5})
    validator.validate(packet)

    missing = validator.missing_enabled_sensors(packet)
    assert "ph_level" in missing
    assert "water_temperature" in missing
    assert "dissolved_oxygen" not in missing
