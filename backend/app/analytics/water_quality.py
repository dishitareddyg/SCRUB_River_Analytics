"""Water-quality derived-parameter calculators.

Contains:
    - :class:`TdsCalculator` (registry key ``"tds"``)
    - :class:`SalinityCalculator` (registry key ``"salinity"``)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig


@register("tds")
class TdsCalculator(BaseCalculator):
    """Estimates Total Dissolved Solids (TDS) from electrical conductivity."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="tds",
            display_name="Total Dissolved Solids",
            formula_name="Conductivity-to-TDS empirical conversion (Hem, 1985)",
            reference=(
                "Hem, J.D. (1985), 'Study and Interpretation of the Chemical "
                "Characteristics of Natural Water', USGS Water-Supply Paper "
                "2254, 3rd ed., p. 66."
            ),
            output_unit="mg/L",
            input_units={"conductivity": "uS/cm"},
            required_inputs=("conductivity",),
            optional_inputs=(),
            assumptions=(
                "A single, site-independent conversion factor "
                "(conductivity_to_tds_factor, configured in analytics.yaml) "
                "relates conductivity to TDS.",
            ),
            limitations=(
                "The conversion factor varies with the ionic composition of "
                "the water and is only an approximation; it should be "
                "recalibrated per site against gravimetric TDS samples for "
                "high-accuracy use.",
            ),
            valid_ranges={"conductivity": (0.0, 20000.0)},
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute TDS from conductivity.

        Args:
            inputs: Validated input mapping (``conductivity`` present).
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        conductivity = inputs["conductivity"]
        value = equations.conductivity_to_tds(
            conductivity_us_cm=conductivity,
            conversion_factor=config.tds.conductivity_to_tds_factor,
        )
        return value, 0.8, []


@register("salinity")
class SalinityCalculator(BaseCalculator):
    """Estimates practical salinity from conductivity and temperature."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="salinity",
            display_name="Salinity",
            formula_name="Practical Salinity Scale 1978 (PSS-78)",
            reference=(
                "Fofonoff, N.P. and Millard, R.C. Jr. (1983), 'Algorithms "
                "for computation of fundamental properties of seawater', "
                "UNESCO Technical Papers in Marine Science No. 44."
            ),
            output_unit="PSU",
            input_units={"conductivity": "uS/cm", "water_temperature": "C"},
            required_inputs=("conductivity", "water_temperature"),
            optional_inputs=(),
            assumptions=(
                "Gauge pressure is assumed to be 0 dbar (surface); the "
                "PSS-78 pressure-correction term is not applied for "
                "shallow river deployments.",
            ),
            limitations=(
                "PSS-78 is formally validated over 2-42 PSU (oceanic "
                "range). For typical freshwater rivers (< 2 PSU) this is "
                "still the standard published conductivity-to-salinity "
                "relationship, but absolute accuracy degrades toward the "
                "low end of the scale.",
            ),
            valid_ranges={"conductivity": (0.0, 20000.0), "water_temperature": (-5.0, 45.0)},
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute practical salinity from conductivity and temperature.

        Args:
            inputs: Validated input mapping (``conductivity`` and
                ``water_temperature`` present).
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        conductivity = inputs["conductivity"]
        temperature = inputs["water_temperature"]
        value = equations.practical_salinity_pss78(
            conductivity_us_cm=conductivity,
            temperature_c=temperature,
            reference_conductivity_us_cm=config.salinity.reference_conductivity_us_cm,
            pressure_dbar=config.salinity.reference_pressure_dbar,
        )
        warnings: List[str] = []
        confidence = 0.75
        if value < 2.0:
            confidence = 0.5
            warnings.append(
                "Computed salinity is below PSS-78's validated 2-42 PSU "
                "range; treat the result as an order-of-magnitude estimate."
            )
        return value, confidence, warnings
