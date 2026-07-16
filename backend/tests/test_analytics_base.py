"""Tests for :mod:`app.analytics.result` and :mod:`app.analytics.base`."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pytest

from app.analytics.base import BaseCalculator, CalculatorMetadata, NotComputableError
from app.analytics.config import AnalyticsConfig
from app.analytics.result import CalculationResult, CalculationStatus
from tests.analytics_test_helpers import base_analytics_config


class _DummyCalculator(BaseCalculator):
    """A minimal calculator for exercising BaseCalculator.calculate()."""

    def __init__(self, *, raises: Optional[Exception] = None) -> None:
        self._raises = raises

    def metadata(self) -> CalculatorMetadata:
        return CalculatorMetadata(
            key="dummy",
            display_name="Dummy",
            formula_name="x + y",
            reference="N/A (test fixture)",
            output_unit="unit",
            input_units={"x": "unit", "y": "unit"},
            required_inputs=("x", "y"),
            optional_inputs=(),
            assumptions=("none",),
            limitations=("none",),
            valid_ranges={"x": (0.0, 10.0)},
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        if self._raises is not None:
            raise self._raises
        return inputs["x"] + inputs["y"], 1.0, []


@pytest.fixture
def config() -> AnalyticsConfig:
    return base_analytics_config()


def test_calculate_ok(config: AnalyticsConfig) -> None:
    """A fully-satisfied calculation should return status OK with the right value."""
    result = _DummyCalculator().calculate({"x": 2.0, "y": 3.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value == 5.0
    assert result.unit == "unit"
    assert result.confidence == 1.0
    assert result.missing_inputs == []


def test_calculate_missing_required_input(config: AnalyticsConfig) -> None:
    """A missing required input should short-circuit to NOT_COMPUTABLE."""
    result = _DummyCalculator().calculate({"x": 2.0}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.value is None
    assert "y" in result.missing_inputs


def test_calculate_none_required_input_is_missing(config: AnalyticsConfig) -> None:
    """An explicit None value counts the same as an absent key."""
    result = _DummyCalculator().calculate({"x": 2.0, "y": None}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["y"]


def test_calculate_out_of_range_input_adds_warning(config: AnalyticsConfig) -> None:
    """An input outside its documented valid range should still compute, with a warning."""
    result = _DummyCalculator().calculate({"x": 999.0, "y": 1.0}, config)
    assert result.status is CalculationStatus.OK
    assert result.value == 1000.0
    assert any("outside the documented valid range" in w for w in result.warnings)


def test_calculate_not_computable_error_from_compute(config: AnalyticsConfig) -> None:
    """A NotComputableError raised inside _compute maps to NOT_COMPUTABLE, not ERROR."""
    calculator = _DummyCalculator(raises=NotComputableError(missing=["site configuration"]))
    result = calculator.calculate({"x": 1.0, "y": 1.0}, config)
    assert result.status is CalculationStatus.NOT_COMPUTABLE
    assert result.missing_inputs == ["site configuration"]


def test_calculate_unexpected_exception_maps_to_error(config: AnalyticsConfig) -> None:
    """Any other exception from _compute should map to ERROR, never propagate."""
    calculator = _DummyCalculator(raises=ZeroDivisionError("boom"))
    result = calculator.calculate({"x": 1.0, "y": 1.0}, config)
    assert result.status is CalculationStatus.ERROR
    assert result.value is None
    assert "boom" in result.error_message


def test_calculate_never_raises(config: AnalyticsConfig) -> None:
    """calculate() must never propagate an exception to the caller."""
    calculator = _DummyCalculator(raises=RuntimeError("should be caught"))
    try:
        result = calculator.calculate({"x": 1.0, "y": 1.0}, config)
    except Exception:  # noqa: BLE001
        pytest.fail("calculate() must not raise")
    assert result.status is CalculationStatus.ERROR


def test_result_to_dict_round_trips_fields() -> None:
    """to_dict() should expose every field in a JSON-friendly form."""
    result = CalculationResult(
        parameter="tds",
        status=CalculationStatus.OK,
        value=325.0,
        unit="mg/L",
        confidence=0.8,
        formula_used="Conductivity-to-TDS",
        reference="Hem (1985)",
    )
    payload = result.to_dict()
    assert payload["parameter"] == "tds"
    assert payload["status"] == "OK"
    assert payload["value"] == 325.0
    assert isinstance(payload["timestamp"], str)
    assert result.is_ok is True


def test_result_is_ok_false_when_not_computable() -> None:
    """is_ok should be False for any non-OK status."""
    result = CalculationResult(parameter="tds", status=CalculationStatus.NOT_COMPUTABLE)
    assert result.is_ok is False
