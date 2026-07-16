"""Unit tests for :mod:`app.serial.packet_parser`."""

from __future__ import annotations

import json

from app.serial.packet_parser import PacketParser


def _make_line(**overrides: object) -> str:
    """Build a JSON packet line, allowing individual fields to be overridden.

    Args:
        **overrides: Fields to override in the default packet payload.

    Returns:
        A JSON-encoded string suitable for feeding to
        :meth:`PacketParser.parse`.
    """
    payload = {
        "timestamp": "2026-07-12T09:30:00Z",
        "device_id": "river-bot-01",
        "sequence": 1,
        "sensors": {"do": 6.5, "ph": 7.1},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_valid_packet_returns_sensor_packet() -> None:
    """A well-formed JSON line should parse into a populated SensorPacket."""
    parser = PacketParser()
    packet = parser.parse(_make_line())

    assert packet is not None
    assert packet.device_id == "river-bot-01"
    assert packet.sequence == 1
    assert packet.timestamp is not None
    assert packet.sensors_raw == {"do": 6.5, "ph": 7.1}


def test_parse_malformed_json_returns_none() -> None:
    """Malformed JSON must be dropped, never raise, and return None."""
    parser = PacketParser()
    assert parser.parse("{not valid json") is None
    assert parser.parse("") is None
    assert parser.parse("   ") is None


def test_parse_non_object_json_returns_none() -> None:
    """A JSON array or scalar (not an object) should be rejected."""
    parser = PacketParser()
    assert parser.parse("[1, 2, 3]") is None
    assert parser.parse("42") is None
    assert parser.parse('"just a string"') is None


def test_parse_ignores_unknown_top_level_fields() -> None:
    """Unrecognized top-level fields must not break parsing."""
    parser = PacketParser()
    packet = parser.parse(_make_line(firmware_version="1.2.3", battery=87))

    assert packet is not None
    assert packet.raw["firmware_version"] == "1.2.3"
    assert packet.device_id == "river-bot-01"


def test_parse_missing_sensors_object_defaults_to_empty() -> None:
    """A packet missing/invalid 'sensors' should parse with an empty dict."""
    parser = PacketParser()
    packet = parser.parse(_make_line(sensors="not-a-dict"))

    assert packet is not None
    assert packet.sensors_raw == {}


def test_parse_missing_sequence_results_in_none_sequence() -> None:
    """A non-numeric sequence value should not raise, just be None."""
    parser = PacketParser()
    packet = parser.parse(_make_line(sequence="not-a-number"))

    assert packet is not None
    assert packet.sequence is None


def test_parse_unparseable_timestamp_is_preserved_as_raw_but_none_parsed() -> None:
    """An unparseable timestamp keeps the raw string but parses to None."""
    parser = PacketParser()
    packet = parser.parse(_make_line(timestamp="not-a-timestamp"))

    assert packet is not None
    assert packet.timestamp_raw == "not-a-timestamp"
    assert packet.timestamp is None


def test_parse_accepts_epoch_seconds_timestamp() -> None:
    """Numeric (epoch seconds) timestamps should also parse successfully."""
    parser = PacketParser()
    packet = parser.parse(_make_line(timestamp=1_752_000_000))

    assert packet is not None
    assert packet.timestamp is not None
