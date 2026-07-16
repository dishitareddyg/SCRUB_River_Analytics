"""Tests for :mod:`app.analytics.calculator_registry`."""

from __future__ import annotations

import pytest

from app.analytics.base import BaseCalculator, CalculatorMetadata
from app.analytics.calculator_registry import (
    all_calculators,
    get_calculator,
    is_registered,
    register,
    registered_keys,
)
from app.utils.exceptions import ConfigurationError


class _MinimalCalculator(BaseCalculator):
    def metadata(self) -> CalculatorMetadata:
        return CalculatorMetadata(
            key="_test_minimal",
            display_name="Minimal",
            formula_name="const",
            reference="N/A",
            output_unit="unit",
            input_units={},
            required_inputs=(),
            optional_inputs=(),
            assumptions=(),
            limitations=(),
            valid_ranges={},
        )

    def _compute(self, inputs, config):
        return 1.0, 1.0, []


def test_engine_calculators_are_all_registered() -> None:
    """Importing the engine should register every documented derived parameter."""
    import app.analytics.analytics_engine  # noqa: F401  (ensures registration side effects ran)

    expected = {
        "tds",
        "salinity",
        "oxygen_saturation",
        "oxygen_deficit",
        "water_density",
        "river_width",
        "cross_sectional_area",
        "wetted_perimeter",
        "hydraulic_radius",
        "hydraulic_depth",
        "flow_velocity",
        "river_discharge",
        "sediment_load",
    }
    assert expected.issubset(set(registered_keys()))


def test_register_decorator_adds_to_registry() -> None:
    """The @register decorator should make a calculator retrievable by key."""
    register("_test_minimal")(_MinimalCalculator)
    assert is_registered("_test_minimal")
    assert isinstance(get_calculator("_test_minimal"), _MinimalCalculator)
    assert "_test_minimal" in all_calculators()


def test_get_calculator_unknown_key_raises_key_error() -> None:
    """Requesting an unregistered key should raise KeyError, not fail silently."""
    with pytest.raises(KeyError):
        get_calculator("_this_key_does_not_exist")


def test_duplicate_registration_with_different_class_raises() -> None:
    """Registering two different classes under the same key should be rejected."""

    class _OtherCalculator(BaseCalculator):
        def metadata(self) -> CalculatorMetadata:
            return CalculatorMetadata(
                key="_test_minimal",
                display_name="Other",
                formula_name="const",
                reference="N/A",
                output_unit="unit",
                input_units={},
                required_inputs=(),
                optional_inputs=(),
                assumptions=(),
                limitations=(),
                valid_ranges={},
            )

        def _compute(self, inputs, config):
            return 2.0, 1.0, []

    register("_test_minimal")(_MinimalCalculator)  # first registration (idempotent, same class)
    with pytest.raises(ConfigurationError):
        register("_test_minimal")(_OtherCalculator)
