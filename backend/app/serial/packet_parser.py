"""Packet parser.

Converts a raw line of text received over serial into a structured
:class:`~app.serial.sensor_packet.SensorPacket`. Parsing is
deliberately tolerant: malformed JSON is rejected without raising,
missing fields are handled gracefully, and unknown top-level or
sensor fields are preserved rather than discarded, so that future
sensor additions never require a code change here.

This module performs *structural* parsing only. Domain validation
(ranges, duplicates, ordering, unknown sensor detection) is the
responsibility of :mod:`app.serial.packet_validator`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.serial.sensor_packet import SensorPacket
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EXPECTED_TOP_LEVEL_FIELDS = {"timestamp", "device_id", "sequence", "sensors"}


class PacketParser:
    """Parses raw serial lines into :class:`SensorPacket` objects."""

    def parse(self, raw_line: str) -> Optional[SensorPacket]:
        """Parse a single raw line of text into a :class:`SensorPacket`.

        Args:
            raw_line: One line of text read from the serial port,
                expected to contain a single JSON object.

        Returns:
            A :class:`SensorPacket` on success, or ``None`` if the
            line could not be parsed as valid JSON (the caller should
            treat this as a dropped packet, not a fatal error).
        """
        line = raw_line.strip()
        if not line:
            return None

        try:
            decoded: Dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(f"Discarding malformed JSON packet: {exc} | raw={line!r}")
            return None

        if not isinstance(decoded, dict):
            logger.warning(f"Discarding packet: expected a JSON object, got {type(decoded).__name__}")
            return None

        unknown_top_level = set(decoded.keys()) - _EXPECTED_TOP_LEVEL_FIELDS
        if unknown_top_level:
            logger.debug(
                f"Packet contains unrecognized top-level fields (ignored): {sorted(unknown_top_level)}"
            )

        device_id = decoded.get("device_id")
        sequence = self._coerce_int(decoded.get("sequence"))
        timestamp_raw = decoded.get("timestamp")
        timestamp = self._parse_timestamp(timestamp_raw)

        sensors_raw = decoded.get("sensors")
        if not isinstance(sensors_raw, dict):
            logger.warning("Packet missing a valid 'sensors' object; treating as empty.")
            sensors_raw = {}

        return SensorPacket(
            device_id=str(device_id) if device_id is not None else None,
            sequence=sequence,
            timestamp_raw=str(timestamp_raw) if timestamp_raw is not None else None,
            timestamp=timestamp,
            sensors_raw=sensors_raw,
            raw=decoded,
        )

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        """Best-effort conversion of a value to ``int``.

        Args:
            value: The raw value to convert.

        Returns:
            The converted integer, or ``None`` if conversion failed.
        """
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Best-effort parsing of a packet timestamp.

        Supports ISO-8601 strings (e.g. ``"2026-07-12T09:30:00Z"``)
        and raw Unix epoch seconds. Any other format is treated as
        unparseable rather than raising.

        Args:
            value: The raw timestamp value from the packet.

        Returns:
            A parsed :class:`datetime`, or ``None`` if parsing failed.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value)
            except (OverflowError, OSError, ValueError):
                return None

        if isinstance(value, str):
            text = value.strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                logger.debug(f"Could not parse packet timestamp: {value!r}")
                return None

        return None
