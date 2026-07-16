"""Packet validator.

Performs domain-level validation of a structurally-parsed
:class:`~app.serial.sensor_packet.SensorPacket`: required fields,
per-device sequence ordering, duplicate detection, sensor field
resolution (via :class:`~app.serial.sensor_registry.SensorRegistry`),
numeric type checks, and range checks.

This module never touches the database and never calculates derived
values - it only decides whether a packet (and its individual sensor
readings) are trustworthy enough to be queued for downstream modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.serial.sensor_packet import SensorPacket, SensorReading
from app.serial.sensor_registry import SensorRegistry
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_TRACKED_DEVICES = 32
"""Safety bound on the number of distinct devices tracked for
sequence/duplicate detection, to prevent unbounded memory growth if a
misbehaving device sends spurious device_id values."""


@dataclass
class ValidationResult:
    """Outcome of validating a single :class:`SensorPacket`.

    Attributes:
        is_valid: ``True`` if the packet passed all *fatal* checks
            (structure, required fields) and is safe to queue.
            Individual sensor readings may still be individually
            invalid/unknown without failing the whole packet.
        errors: Fatal validation errors that caused ``is_valid`` to be
            ``False``.
        warnings: Non-fatal issues (e.g. one unknown sensor field)
            that do not prevent queuing the packet.
    """

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PacketValidator:
    """Validates :class:`SensorPacket` instances against domain rules.

    The validator is stateful per :class:`PacketValidator` instance:
    it remembers the last sequence number and a small history of seen
    ``(device_id, sequence)`` pairs per device in order to detect
    duplicate and out-of-order packets. A single validator instance
    should be reused for the lifetime of a serial connection.
    """

    def __init__(self, registry: SensorRegistry) -> None:
        """Initialize the validator.

        Args:
            registry: The sensor registry used to resolve and range
                check sensor fields.
        """
        self._registry = registry
        self._last_sequence: Dict[str, int] = {}
        self._seen_sequences: Dict[str, set[int]] = {}

    def validate(self, packet: SensorPacket) -> ValidationResult:
        """Validate a packet and populate its resolved sensor readings.

        Args:
            packet: The structurally-parsed packet to validate. Its
                ``readings`` list is populated in place with resolved
                :class:`SensorReading` entries.

        Returns:
            A :class:`ValidationResult` describing whether the packet
            is safe to queue, along with any errors/warnings.
        """
        errors: List[str] = []
        warnings: List[str] = []

        self._validate_structure(packet, errors)

        if packet.device_id:
            self._validate_sequence(packet, warnings)

        packet.readings = self._resolve_readings(packet.sensors_raw, warnings)

        is_valid = not errors
        if warnings:
            logger.debug(f"Packet validated with warnings: {warnings}")
        if errors:
            logger.warning(f"Packet failed validation: {errors}")

        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

    def _validate_structure(self, packet: SensorPacket, errors: List[str]) -> None:
        """Check required top-level fields are present.

        Args:
            packet: The packet to validate.
            errors: Mutable list that fatal errors are appended to.
        """
        if not packet.device_id:
            errors.append("Missing required field: device_id")
        if packet.sequence is None:
            errors.append("Missing or non-numeric required field: sequence")
        if not packet.timestamp_raw:
            errors.append("Missing required field: timestamp")
        elif packet.timestamp is None:
            errors.append(f"Unparseable timestamp: {packet.timestamp_raw!r}")
        if not packet.sensors_raw:
            errors.append("Packet contains no sensor readings")

    def _validate_sequence(self, packet: SensorPacket, warnings: List[str]) -> None:
        """Check for duplicate or out-of-order sequence numbers.

        Args:
            packet: The packet to validate.
            warnings: Mutable list that non-fatal warnings are
                appended to.
        """
        device_id = packet.device_id
        sequence = packet.sequence
        if device_id is None or sequence is None:
            return

        if device_id not in self._seen_sequences:
            if len(self._seen_sequences) >= _MAX_TRACKED_DEVICES:
                logger.warning(
                    f"Tracked device limit reached; not tracking sequence state for '{device_id}'."
                )
                return
            self._seen_sequences[device_id] = set()

        seen = self._seen_sequences[device_id]

        if sequence in seen:
            warnings.append(f"Duplicate packet detected: device={device_id} sequence={sequence}")
            return

        last_sequence = self._last_sequence.get(device_id)
        if last_sequence is not None and sequence <= last_sequence:
            warnings.append(
                f"Out-of-order packet: device={device_id} sequence={sequence} "
                f"(last seen {last_sequence})"
            )

        seen.add(sequence)
        # Bound memory usage of the dedup set.
        if len(seen) > 1000:
            seen.clear()
            seen.add(sequence)

        self._last_sequence[device_id] = sequence

    def _resolve_readings(
        self, sensors_raw: Dict[str, Any], warnings: List[str]
    ) -> List[SensorReading]:
        """Resolve and range-check each raw sensor field.

        Unknown sensor fields are preserved as :class:`SensorReading`
        entries with ``is_known=False`` rather than dropped, so future
        sensors can be observed even before ``sensors.yaml`` is
        updated for them - they simply won't be range-validated.

        Args:
            sensors_raw: The raw ``sensors`` object from the packet.
            warnings: Mutable list that non-fatal warnings are
                appended to.

        Returns:
            A list of resolved :class:`SensorReading` entries.
        """
        readings: List[SensorReading] = []

        for field_name, value in sensors_raw.items():
            definition = self._registry.resolve(field_name)

            if definition is None:
                warnings.append(f"Unknown sensor field (not in sensors.yaml): '{field_name}'")
                readings.append(
                    SensorReading(
                        field_name=field_name,
                        sensor_name=None,
                        value=value,
                        is_known=False,
                        is_valid=False,
                        error="Unrecognized sensor field",
                    )
                )
                continue

            reading = self._validate_reading(field_name, value, definition, warnings)
            readings.append(reading)

        return readings

    def _validate_reading(
        self, field_name: str, value: Any, definition: Any, warnings: List[str]
    ) -> SensorReading:
        """Validate a single known sensor's value.

        Args:
            field_name: The raw field name from the packet.
            value: The raw value associated with the field.
            definition: The resolved
                :class:`~app.serial.sensor_registry.SensorDefinition`.
            warnings: Mutable list that non-fatal warnings are
                appended to.

        Returns:
            A populated :class:`SensorReading`.
        """
        if not definition.enabled:
            return SensorReading(
                field_name=field_name,
                sensor_name=definition.sensor_name,
                value=value,
                unit=definition.unit,
                is_known=True,
                is_valid=False,
                error="Sensor is disabled in sensors.yaml",
            )

        # Compound (non-scalar) readings, e.g. GPS {latitude, longitude},
        # are not range-checked here - only presence/type is confirmed.
        if isinstance(value, dict):
            if not value:
                warnings.append(f"Empty compound reading for sensor '{definition.sensor_name}'")
                return SensorReading(
                    field_name=field_name,
                    sensor_name=definition.sensor_name,
                    value=value,
                    unit=definition.unit,
                    is_known=True,
                    is_valid=False,
                    error="Empty compound value",
                )
            return SensorReading(
                field_name=field_name,
                sensor_name=definition.sensor_name,
                value=value,
                unit=definition.unit,
                is_known=True,
                is_valid=True,
            )

        if not isinstance(value, (int, float)) or isinstance(value, bool):
            warnings.append(
                f"Non-numeric value for sensor '{definition.sensor_name}': {value!r}"
            )
            return SensorReading(
                field_name=field_name,
                sensor_name=definition.sensor_name,
                value=value,
                unit=definition.unit,
                is_known=True,
                is_valid=False,
                error="Expected a numeric value",
            )

        if not definition.is_within_range(float(value)):
            warnings.append(
                f"Value out of range for sensor '{definition.sensor_name}': {value} "
                f"(expected {definition.minimum_value}..{definition.maximum_value})"
            )
            return SensorReading(
                field_name=field_name,
                sensor_name=definition.sensor_name,
                value=value,
                unit=definition.unit,
                is_known=True,
                is_valid=False,
                error="Value outside configured valid range",
            )

        return SensorReading(
            field_name=field_name,
            sensor_name=definition.sensor_name,
            value=value,
            unit=definition.unit,
            is_known=True,
            is_valid=True,
        )

    def missing_enabled_sensors(self, packet: SensorPacket) -> List[str]:
        """Return canonical names of enabled sensors absent from a packet.

        Useful for diagnostics/status reporting; does not affect
        ``ValidationResult.is_valid``, since a device may legitimately
        omit a sensor temporarily (e.g. a slower-sampling channel).

        Args:
            packet: The packet whose readings should be checked.

        Returns:
            A list of canonical sensor names that are enabled in
            ``sensors.yaml`` but were not present in the packet.
        """
        present = {reading.sensor_name for reading in packet.readings if reading.sensor_name}
        return [
            definition.sensor_name
            for definition in self._registry.enabled_sensors()
            if definition.sensor_name not in present
        ]
