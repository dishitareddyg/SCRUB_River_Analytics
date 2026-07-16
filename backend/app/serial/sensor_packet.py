"""Sensor packet data model.

Defines the structured, in-memory representation of a single packet
received from the Arduino Uno, along with the per-field validation
results attached to it once :mod:`app.serial.packet_validator` has
run. Nothing in this module writes to a database or performs
analytics - it is a pure data container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SensorReading:
    """A single, resolved sensor reading extracted from a packet.

    Attributes:
        field_name: The raw field name as it appeared in the JSON
            packet (e.g. ``"do"``).
        sensor_name: The canonical sensor name it resolved to via the
            sensor registry, or ``None`` if unrecognized.
        value: The raw value from the packet (numeric, or a nested
            dict for compound sensors such as GPS).
        unit: Unit of measurement, if the sensor was recognized.
        is_known: Whether ``field_name`` resolved to a configured
            sensor.
        is_valid: Whether the reading passed validation (type, range).
        error: Human readable validation error, if any.
    """

    field_name: str
    sensor_name: Optional[str]
    value: Any
    unit: Optional[str] = None
    is_known: bool = False
    is_valid: bool = True
    error: Optional[str] = None


@dataclass
class SensorPacket:
    """Structured representation of one Arduino telemetry packet.

    Attributes:
        device_id: Identifier of the transmitting device, as reported
            in the packet.
        sequence: Monotonically increasing packet sequence number, as
            reported by the device.
        timestamp_raw: The raw ``timestamp`` string as received.
        timestamp: Best-effort parsed timestamp, or ``None`` if it
            could not be parsed.
        received_at: Local UTC time this packet was received/parsed by
            the backend (independent of the device's own clock).
        sensors_raw: The raw ``sensors`` object from the packet,
            unmodified, including any unrecognized fields.
        readings: Resolved :class:`SensorReading` entries, populated
            by the packet validator.
        raw: The full, original decoded JSON object.
    """

    device_id: Optional[str]
    sequence: Optional[int]
    timestamp_raw: Optional[str]
    timestamp: Optional[datetime]
    sensors_raw: Dict[str, Any]
    raw: Dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    readings: List[SensorReading] = field(default_factory=list)

    def get_reading(self, sensor_name: str) -> Optional[SensorReading]:
        """Look up a resolved reading by canonical sensor name.

        Args:
            sensor_name: The canonical sensor name to look up.

        Returns:
            The matching :class:`SensorReading`, or ``None`` if not
            present.
        """
        for reading in self.readings:
            if reading.sensor_name == sensor_name:
                return reading
        return None
