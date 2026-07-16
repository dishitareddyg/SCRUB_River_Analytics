"""Common calculator interface.

Every derived-parameter calculator (TDS, salinity, oxygen saturation,
river discharge, ...) implements :class:`BaseCalculator`. This is the
sole contract the rest of the platform (the registry, the engine, and
every future consumer) depends on - individual equations can be
swapped, recalibrated, or replaced without changing any calling code,
as long as the new implementation still satisfies this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.analytics.result import CalculationResult, CalculationStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CalculatorMetadata:
    """Descriptive, machine-and-human-readable metadata for a calculator.

    Every calculator must expose this via :meth:`BaseCalculator.metadata`
    so that formula provenance is always inspectable at runtime (by a
    future API endpoint, a report generator, or a developer).

    Attributes:
        key: The calculator's registry key (e.g. ``"tds"``).
        display_name: Human friendly parameter name.
        formula_name: Name of the formula/equation implemented.
        reference: Full scientific/engineering citation.
        output_unit: Unit of the computed output value.
        input_units: Mapping of input name -> unit, for every input
            (required and optional) the calculator can consume.
        required_inputs: Names of inputs without which the
            calculation cannot proceed.
        optional_inputs: Names of inputs that refine the result (e.g.
            enable a correction term) but are not strictly required.
        assumptions: Simplifications or fixed assumptions baked into
            the implementation.
        limitations: Known limitations of the formula/implementation.
        valid_ranges: Mapping of input name -> ``(min, max)`` tuple
            describing the formula's documented valid operating range
            for that input. Values outside this range are still
            computed but flagged with a warning and reduced
            confidence.
    """

    key: str
    display_name: str
    formula_name: str
    reference: str
    output_unit: str
    input_units: Dict[str, str]
    required_inputs: Tuple[str, ...]
    optional_inputs: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    limitations: Tuple[str, ...]
    valid_ranges: Dict[str, Tuple[float, float]]


class NotComputableError(Exception):
    """Raised by a calculator's ``_compute`` when it cannot proceed.

    Distinct from letting an arbitrary exception propagate: this is
    for cases discovered *during* computation - typically missing
    site-survey configuration (e.g. an unconfigured channel bed
    width) rather than a missing sensor reading (which
    :meth:`BaseCalculator.validate_inputs` already screens out before
    ``_compute`` is even called). :meth:`BaseCalculator.calculate`
    converts this into a :attr:`CalculationStatus.NOT_COMPUTABLE`
    result (not :attr:`CalculationStatus.ERROR`), with ``missing``
    merged into the result's ``missing_inputs``.

    Attributes:
        missing: Names/descriptions of the missing configuration or
            derived values that prevented computation.
    """

    def __init__(self, missing: List[str]) -> None:
        """Initialize the error.

        Args:
            missing: Names/descriptions of what is missing.
        """
        super().__init__(f"Not computable; missing: {missing}")
        self.missing = missing


class BaseCalculator(ABC):
    """Abstract base class for every derived-parameter calculator.

    Subclasses implement :meth:`metadata` and :meth:`_compute`.
    :meth:`calculate` orchestrates input validation, range checking,
    error handling, and building the final :class:`CalculationResult`
    - subclasses never need to construct a :class:`CalculationResult`
    themselves for the missing-input or error paths.
    """

    @abstractmethod
    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The calculator's :class:`CalculatorMetadata`.
        """
        raise NotImplementedError

    def required_inputs(self) -> Tuple[str, ...]:
        """Names of inputs without which this calculator cannot run.

        Returns:
            A tuple of required input names, taken from
            :meth:`metadata`.
        """
        return self.metadata().required_inputs

    def optional_inputs(self) -> Tuple[str, ...]:
        """Names of inputs that refine but are not required for this calculator.

        Returns:
            A tuple of optional input names, taken from
            :meth:`metadata`.
        """
        return self.metadata().optional_inputs

    def validate_inputs(self, inputs: Mapping[str, Optional[float]]) -> List[str]:
        """Determine which required inputs are missing/unusable.

        Args:
            inputs: Mapping of input name -> value (``None`` or
                absent means "unavailable").

        Returns:
            A list of required input names that are missing or
            ``None``. Empty if every required input is present.
        """
        missing: List[str] = []
        for name in self.required_inputs():
            value = inputs.get(name)
            if value is None:
                missing.append(name)
        return missing

    def calculate(
        self,
        inputs: Mapping[str, Optional[float]],
        config: Optional[AnalyticsConfig] = None,
    ) -> CalculationResult:
        """Validate inputs, compute the result, and package it.

        Args:
            inputs: Mapping of input name -> latest available value
                (``None``/absent for unavailable inputs).
            config: The :class:`AnalyticsConfig` to use. Defaults to
                the process-wide cached config from
                :func:`app.analytics.config.get_analytics_config`.

        Returns:
            A fully populated :class:`CalculationResult`. Never
            raises: any exception from :meth:`_compute` is caught and
            reported as an :attr:`CalculationStatus.ERROR` result.
        """
        metadata = self.metadata()
        active_config = config or get_analytics_config()

        logger.info(f"Calculation started: parameter={metadata.key}")

        missing = self.validate_inputs(inputs)
        if missing:
            logger.warning(
                f"Calculation not computable: parameter={metadata.key} missing_inputs={missing}"
            )
            return CalculationResult(
                parameter=metadata.key,
                status=CalculationStatus.NOT_COMPUTABLE,
                unit=metadata.output_unit,
                missing_inputs=missing,
                formula_used=metadata.formula_name,
                reference=metadata.reference,
                inputs_used=_used_subset(inputs, metadata),
            )

        used_inputs = _used_subset(inputs, metadata)
        warnings: List[str] = list(_range_warnings(used_inputs, metadata))

        try:
            value, confidence, compute_warnings = self._compute(dict(inputs), active_config)
        except NotComputableError as exc:
            logger.warning(
                f"Calculation not computable: parameter={metadata.key} missing={exc.missing}"
            )
            return CalculationResult(
                parameter=metadata.key,
                status=CalculationStatus.NOT_COMPUTABLE,
                unit=metadata.output_unit,
                missing_inputs=list(exc.missing),
                formula_used=metadata.formula_name,
                reference=metadata.reference,
                inputs_used=used_inputs,
            )
        except Exception as exc:  # noqa: BLE001 - deliberately broad: never crash the engine
            logger.error(f"Calculation failed: parameter={metadata.key} error={exc}")
            return CalculationResult(
                parameter=metadata.key,
                status=CalculationStatus.ERROR,
                unit=metadata.output_unit,
                formula_used=metadata.formula_name,
                reference=metadata.reference,
                inputs_used=used_inputs,
                error_message=str(exc),
            )

        warnings.extend(compute_warnings)
        logger.info(f"Calculation completed: parameter={metadata.key} value={value}")

        return CalculationResult(
            parameter=metadata.key,
            status=CalculationStatus.OK,
            value=value,
            unit=metadata.output_unit,
            confidence=confidence,
            formula_used=metadata.formula_name,
            reference=metadata.reference,
            warnings=warnings,
            inputs_used=used_inputs,
        )

    @abstractmethod
    def _compute(
        self,
        inputs: Dict[str, Optional[float]],
        config: AnalyticsConfig,
    ) -> Tuple[float, float, List[str]]:
        """Compute the derived value from validated inputs.

        Only called once every required input has already been
        confirmed present by :meth:`calculate` - implementations do
        not need to re-check for ``None`` on required inputs, though
        optional inputs may still be ``None`` and must be handled.

        Args:
            inputs: The full input mapping (required inputs are
                guaranteed non-``None``).
            config: The active :class:`AnalyticsConfig`.

        Returns:
            A ``(value, confidence, warnings)`` tuple: the computed
            value, a ``0.0``-``1.0`` confidence score, and a list of
            any non-fatal warning strings.

        Raises:
            Exception: Any exception propagates up to
                :meth:`calculate`, which converts it into an
                :attr:`CalculationStatus.ERROR` result.
        """
        raise NotImplementedError


def _used_subset(
    inputs: Mapping[str, Optional[float]], metadata: CalculatorMetadata
) -> Dict[str, Any]:
    """Extract only the inputs this calculator declares it can use.

    Args:
        inputs: The full input mapping supplied by the caller.
        metadata: The calculator's metadata.

    Returns:
        A dict containing only keys in the calculator's required or
        optional inputs, for traceability on the result.
    """
    relevant = set(metadata.required_inputs) | set(metadata.optional_inputs)
    return {name: inputs.get(name) for name in relevant if name in inputs}


def _range_warnings(
    used_inputs: Mapping[str, Optional[float]], metadata: CalculatorMetadata
) -> List[str]:
    """Build warnings for any input outside its documented valid range.

    Args:
        used_inputs: The subset of inputs relevant to this calculator.
        metadata: The calculator's metadata (holds ``valid_ranges``).

    Returns:
        A list of human readable warning strings, one per
        out-of-range input.
    """
    warnings: List[str] = []
    for name, (low, high) in metadata.valid_ranges.items():
        value = used_inputs.get(name)
        if value is None:
            continue
        if value < low or value > high:
            warnings.append(
                f"Input '{name}'={value} is outside the documented valid range "
                f"[{low}, {high}] for {metadata.formula_name}; result confidence reduced."
            )
    return warnings
