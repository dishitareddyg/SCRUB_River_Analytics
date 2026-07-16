"""Unit tests for :mod:`app.serial.sensor_registry`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.serial.sensor_registry import SensorRegistry
from app.utils.exceptions import ConfigurationError
from tests.serial_test_helpers import build_test_registry


def test_registry_loads_all_configured_sensors(tmp_path: Path) -> None:
    """The registry should load every sensor entry from the YAML file."""
    registry = build_test_registry(tmp_path)
    names = {definition.sensor_name for definition in registry.all_sensors()}

    assert names == {"dissolved_oxygen", "ph_level", "water_temperature", "turbidity"}


def test_registry_resolves_canonical_name_and_alias(tmp_path: Path) -> None:
    """Both the canonical sensor_name and its alias should resolve identically."""
    registry = build_test_registry(tmp_path)

    by_canonical = registry.get("dissolved_oxygen")
    by_alias = registry.resolve("do")

    assert by_canonical is not None
    assert by_alias is not None
    assert by_canonical.sensor_name == by_alias.sensor_name == "dissolved_oxygen"


def test_registry_resolve_returns_none_for_unknown_field(tmp_path: Path) -> None:
    """Resolving an unconfigured field name should return None, not raise."""
    registry = build_test_registry(tmp_path)
    assert registry.resolve("totally_unknown_sensor") is None


def test_registry_enabled_sensors_excludes_disabled(tmp_path: Path) -> None:
    """enabled_sensors() should exclude sensors with enabled: false."""
    registry = build_test_registry(tmp_path)
    enabled_names = {definition.sensor_name for definition in registry.enabled_sensors()}

    assert "turbidity" not in enabled_names
    assert "dissolved_oxygen" in enabled_names


def test_missing_yaml_file_raises_configuration_error(tmp_path: Path) -> None:
    """Pointing the registry at a nonexistent file should raise ConfigurationError."""
    missing_path = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigurationError):
        SensorRegistry(yaml_path=missing_path)


def test_malformed_yaml_raises_configuration_error(tmp_path: Path) -> None:
    """A sensors.yaml with an invalid sensor entry should raise ConfigurationError."""
    bad_path = tmp_path / "sensors.yaml"
    bad_path.write_text(
        "sensors:\n  - sensor_name: broken\n    minimum_value: 0.0\n",  # missing maximum_value
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        SensorRegistry(yaml_path=bad_path)


def test_is_within_range_boundaries(tmp_path: Path) -> None:
    """is_within_range should be inclusive of both boundary values."""
    registry = build_test_registry(tmp_path)
    definition = registry.get("ph_level")

    assert definition is not None
    assert definition.is_within_range(0.0)
    assert definition.is_within_range(14.0)
    assert not definition.is_within_range(-0.01)
    assert not definition.is_within_range(14.01)
