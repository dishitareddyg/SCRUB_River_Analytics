"""Structured calculation results.

Every calculator in the Analytics Engine returns a
:class:`CalculationResult`, regardless of whether the calculation
succeeded, was impossible due to missing inputs, or failed with an
error. This gives every downstream consumer (dashboard, API, ML,
reports) a single, predictable contract to depend on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CalculationStatus(str, Enum):
    """Outcome of a single calculator invocation.

    Attributes:
        OK: The value was computed successfully.
        NOT_COMPUTABLE: Required inputs were missing or out of their
            valid operating range; no value could be produced.
        ERROR: The calculation raised an unexpected error while
            computing (as opposed to simply lacking inputs).
    """

    OK = "OK"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"
    ERROR = "ERROR"


@dataclass
class CalculationResult:
    """The structured outcome of one derived-parameter calculation.

    Attributes:
        parameter: The registry key of the computed parameter (e.g.
            ``"tds"``, ``"river_discharge"``).
        status: The outcome of the calculation.
        value: The computed value, or ``None`` if not computable/errored.
        unit: The unit of ``value`` (e.g. ``"mg/L"``), or ``None``.
        timestamp: When the calculation was performed (UTC).
        confidence: A ``0.0``-``1.0`` confidence score reflecting
            input quality/assumption strength, or ``None`` when not
            computable.
        missing_inputs: Names of any required inputs that were
            unavailable.
        formula_used: Human readable name of the formula/equation
            applied.
        reference: The scientific reference for the formula used.
        warnings: Non-fatal warnings raised during calculation (e.g.
            an input outside its documented valid range, or a
            fallback assumption being used).
        inputs_used: The raw input values actually consumed by the
            calculation, for traceability/debugging.
        error_message: Human readable error description, populated
            only when ``status`` is :attr:`CalculationStatus.ERROR`.
    """

    parameter: str
    status: CalculationStatus
    value: Optional[float] = None
    unit: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: Optional[float] = None
    missing_inputs: List[str] = field(default_factory=list)
    formula_used: Optional[str] = None
    reference: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    inputs_used: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this result into a plain, JSON-friendly dict.

        Returns:
            A dict representation suitable for JSON serialization or
            for handing to a future API/dashboard layer.
        """
        return {
            "parameter": self.parameter,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
            "missing_inputs": list(self.missing_inputs),
            "formula_used": self.formula_used,
            "reference": self.reference,
            "warnings": list(self.warnings),
            "inputs_used": dict(self.inputs_used),
            "error_message": self.error_message,
        }

    @property
    def is_ok(self) -> bool:
        """Whether this result represents a successfully computed value.

        Returns:
            ``True`` if :attr:`status` is :attr:`CalculationStatus.OK`.
        """
        return self.status is CalculationStatus.OK
