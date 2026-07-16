"""Shared helpers for the serial acquisition test suite.

Not a pytest ``conftest.py`` on purpose (it is imported explicitly by
the serial test modules) so it does not interfere with the top-level
``tests/conftest.py`` FastAPI fixtures.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.serial.sensor_registry import SensorRegistry

_TEST_SENSORS_YAML = textwrap.dedent(
    """
    sensors:
      - sensor_name: dissolved_oxygen
        display_name: "Dissolved Oxygen"
        description: "Amount of oxygen dissolved in the water"
        category: dissolved_oxygen
        unit: "mg/L"
        enabled: true
        sampling_interval: 10
        minimum_value: 0.0
        maximum_value: 20.0
        aliases: ["do"]

      - sensor_name: ph_level
        display_name: "pH Level"
        description: "Acidity/alkalinity of the river water"
        category: ph
        unit: "pH"
        enabled: true
        sampling_interval: 5
        minimum_value: 0.0
        maximum_value: 14.0
        aliases: ["ph"]

      - sensor_name: water_temperature
        display_name: "Water Temperature"
        description: "Temperature of the river water"
        category: water_temperature
        unit: "C"
        enabled: true
        sampling_interval: 5
        minimum_value: -5.0
        maximum_value: 45.0

      - sensor_name: turbidity
        display_name: "Turbidity"
        description: "Cloudiness of the water"
        category: turbidity
        unit: "NTU"
        enabled: false
        sampling_interval: 10
        minimum_value: 0.0
        maximum_value: 4000.0
    """
)


def build_test_registry(tmp_path: Path) -> SensorRegistry:
    """Build a :class:`SensorRegistry` from a small, deterministic YAML fixture.

    Args:
        tmp_path: Pytest's per-test temporary directory fixture value.

    Returns:
        A :class:`SensorRegistry` loaded from a temporary
        ``sensors.yaml`` independent of the application's real
        configuration, so tests are unaffected by future edits to the
        real ``sensors.yaml``.
    """
    yaml_path = tmp_path / "sensors.yaml"
    yaml_path.write_text(_TEST_SENSORS_YAML, encoding="utf-8")
    return SensorRegistry(yaml_path=yaml_path)
