"""Sensor registry.

Loads the generic sensor definitions from ``app/config/sensors.yaml``
and exposes them as a lookup table keyed by canonical sensor name (and
by any configured aliases). This is the *only* place in the serial
acquisition subsystem allowed to know sensor identifiers - every other
module resolves sensors through this registry rather than hardcoding
names, units, or ranges in Python.

Adding, renaming, disabling, or re-ranging a sensor only ever requires
editing ``sensors.yaml``; no Python code changes are needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.utils.exceptions import ConfigurationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SENSORS_YAML_PATH = Path(__file__).resolve().parents[1] / "config" / "sensors.yaml"


@dataclass(frozen=True)
class SensorDefinition:
    """Immutable definition of a single configured sensor.

    Attributes:
        sensor_name: Canonical, unique machine-readable identifier.
        display_name: Human friendly name for dashboards/logs.
        description: Short description of what the sensor measures.
        category: Sensor category string (see
            :class:`app.config.constants.SensorCategory`).
        unit: Unit of measurement (e.g. "mg/L", "NTU", "C").
        enabled: Whether this sensor channel is currently active.
        sampling_interval: Expected sampling interval, in seconds.
        minimum_value: Lowest physically valid reading.
        maximum_value: Highest physically valid reading.
        aliases: Alternate JSON field names the firmware may use for
            this sensor (e.g. ``"do"`` for ``dissolved_oxygen``).
    """

    sensor_name: str
    display_name: str
    description: str
    category: str
    unit: str
    enabled: bool
    sampling_interval: int
    minimum_value: float
    maximum_value: float
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def is_within_range(self, value: float) -> bool:
        """Check whether a numeric reading falls within the valid range.

        Args:
            value: The numeric sensor reading to check.

        Returns:
            ``True`` if ``minimum_value <= value <= maximum_value``.
        """
        return self.minimum_value <= value <= self.maximum_value


class SensorRegistry:
    """Loads and indexes sensor definitions from ``sensors.yaml``.

    The registry builds two lookup indexes: one by canonical
    ``sensor_name`` and one by alias, so that incoming packet field
    names (which may use short/legacy names) can be resolved to a
    canonical :class:`SensorDefinition` purely through configuration.
    """

    def __init__(self, yaml_path: Path = _SENSORS_YAML_PATH) -> None:
        """Load sensor definitions from the given YAML file.

        Args:
            yaml_path: Path to the ``sensors.yaml`` configuration
                file.

        Raises:
            ConfigurationError: If the file is missing, malformed, or
                contains invalid sensor entries.
        """
        self._yaml_path = yaml_path
        self._by_name: Dict[str, SensorDefinition] = {}
        self._alias_to_name: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Parse ``sensors.yaml`` and populate the lookup indexes.

        Raises:
            ConfigurationError: If the file is missing, malformed, or
                contains invalid sensor entries.
        """
        if not self._yaml_path.exists():
            raise ConfigurationError(
                f"Sensor configuration file not found: {self._yaml_path}"
            )

        try:
            with self._yaml_path.open("r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(
                f"Failed to parse sensor configuration: {exc}"
            ) from exc

        entries = raw.get("sensors", [])
        if not isinstance(entries, list):
            raise ConfigurationError(
                "sensors.yaml must contain a top-level 'sensors' list."
            )

        for entry in entries:
            try:
                definition = SensorDefinition(
                    sensor_name=str(entry["sensor_name"]),
                    display_name=str(entry.get("display_name", entry["sensor_name"])),
                    description=str(entry.get("description", "")),
                    category=str(entry.get("category", "")),
                    unit=str(entry.get("unit", "")),
                    enabled=bool(entry.get("enabled", False)),
                    sampling_interval=int(entry.get("sampling_interval", 5)),
                    minimum_value=float(entry["minimum_value"]),
                    maximum_value=float(entry["maximum_value"]),
                    aliases=tuple(entry.get("aliases") or ()),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigurationError(
                    f"Invalid sensor entry in sensors.yaml: {entry!r} ({exc})"
                ) from exc

            if definition.sensor_name in self._by_name:
                raise ConfigurationError(
                    f"Duplicate sensor_name in sensors.yaml: {definition.sensor_name}"
                )

            self._by_name[definition.sensor_name] = definition
            self._alias_to_name[definition.sensor_name] = definition.sensor_name
            for alias in definition.aliases:
                if alias in self._alias_to_name:
                    raise ConfigurationError(
                        f"Duplicate sensor alias in sensors.yaml: {alias}"
                    )
                self._alias_to_name[alias] = definition.sensor_name

        logger.info(f"Loaded {len(self._by_name)} sensor definitions from sensors.yaml")

    def resolve(self, field_name: str) -> Optional[SensorDefinition]:
        """Resolve a raw packet field name to its canonical definition.

        Args:
            field_name: The field name as it appears in the incoming
                JSON packet's ``sensors`` object (e.g. ``"do"`` or
                ``"dissolved_oxygen"``).

        Returns:
            The matching :class:`SensorDefinition`, or ``None`` if the
            field name is not recognized by any configured sensor or
            alias.
        """
        canonical_name = self._alias_to_name.get(field_name)
        if canonical_name is None:
            return None
        return self._by_name.get(canonical_name)

    def get(self, sensor_name: str) -> Optional[SensorDefinition]:
        """Return the definition for a canonical sensor name.

        Args:
            sensor_name: The canonical ``sensor_name``.

        Returns:
            The matching :class:`SensorDefinition`, or ``None``.
        """
        return self._by_name.get(sensor_name)

    def enabled_sensors(self) -> List[SensorDefinition]:
        """Return all sensor definitions currently marked as enabled.

        Returns:
            A list of enabled :class:`SensorDefinition` instances.
        """
        return [definition for definition in self._by_name.values() if definition.enabled]

    def all_sensors(self) -> List[SensorDefinition]:
        """Return every configured sensor definition, enabled or not.

        Returns:
            A list of all :class:`SensorDefinition` instances.
        """
        return list(self._by_name.values())


@lru_cache
def get_sensor_registry() -> SensorRegistry:
    """Return a cached, process-wide :class:`SensorRegistry` instance.

    Returns:
        The singleton :class:`SensorRegistry`.
    """
    return SensorRegistry()
