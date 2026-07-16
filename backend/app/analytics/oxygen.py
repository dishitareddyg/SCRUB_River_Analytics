"""Dissolved-oxygen derived-parameter calculators.

Contains:
    - :class:`OxygenSaturationCalculator` (registry key ``"oxygen_saturation"``)
    - :class:`OxygenDeficitCalculator` (registry key ``"oxygen_deficit"``)

Both calculators share the same theoretical DO-saturation-concentration
computation (:func:`_saturation_concentration_mg_l`), which is a
single, non-duplicated composition of the equations in
:mod:`app.analytics.equations`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig

_OPTIONAL_INPUTS: Tuple[str, ...] = ("conductivity", "barometric_pressure")

_ASSUMPTIONS: Tuple[str, ...] = (
    "The theoretical saturation concentration is computed at the "
    "measured water temperature using the Benson-Krause (1984) "
    "freshwater/standard-pressure table.",
    "A salinity correction is applied only when 'conductivity' is "
    "available (salinity is derived internally via PSS-78) and "
    "oxygen.saturation.apply_salinity_correction is enabled in "
    "analytics.yaml; otherwise zero salinity is assumed.",
    "A barometric-pressure correction is applied only when "
    "'barometric_pressure' is available and "
    "oxygen.saturation.apply_pressure_correction is enabled; otherwise "
    "standard sea-level pressure (760 mmHg) is assumed, which "
    "overestimates saturation at elevation.",
)

_LIMITATIONS: Tuple[str, ...] = (
    "The barometric correction is the simplified linear pressure-ratio "
    "form (BP / 760 mmHg); it omits the water-vapor-pressure term of "
    "the full APHA 4500-O G correction, which is a second-order effect "
    "at typical river-monitoring altitudes.",
    "Benson-Krause is documented for 0-40 C freshwater; extrapolation "
    "outside this range is unreliable.",
)


def _saturation_concentration_mg_l(
    inputs: Dict[str, Optional[float]], config: AnalyticsConfig
) -> Tuple[float, List[str]]:
    """Compute the theoretical, corrected DO saturation concentration.

    Composes :func:`app.analytics.equations.oxygen_saturation_concentration_mg_l`
    with the optional salinity and barometric-pressure corrections, per
    ``oxygen.saturation`` settings in ``analytics.yaml``.

    Args:
        inputs: Input mapping; must contain ``water_temperature``. May
            optionally contain ``conductivity`` and
            ``barometric_pressure``.
        config: The active analytics configuration.

    Returns:
        A ``(saturation_concentration_mg_l, warnings)`` tuple.
    """
    warnings: List[str] = []
    temperature = inputs["water_temperature"]
    saturation = equations.oxygen_saturation_concentration_mg_l(temperature)

    conductivity = inputs.get("conductivity")
    if conductivity is not None and config.oxygen_saturation.apply_salinity_correction:
        # Salinity is derived here (not from the "salinity" calculator)
        # to keep each calculator dependent only on raw sensor inputs.
        salinity_psu = equations.practical_salinity_pss78(
            conductivity_us_cm=conductivity,
            temperature_c=temperature,
            reference_conductivity_us_cm=config.salinity.reference_conductivity_us_cm,
            pressure_dbar=config.salinity.reference_pressure_dbar,
        )
        saturation *= equations.oxygen_salinity_correction_factor(salinity_psu, temperature)
    else:
        warnings.append(
            "No conductivity reading available; DO saturation computed "
            "assuming zero salinity (freshwater)."
        )

    barometric_pressure = inputs.get("barometric_pressure")
    if barometric_pressure is not None and config.oxygen_saturation.apply_pressure_correction:
        saturation *= equations.oxygen_pressure_correction_factor(
            barometric_pressure_hpa=barometric_pressure,
            standard_pressure_mmhg=config.oxygen_saturation.standard_pressure_mmhg,
        )
    else:
        warnings.append(
            "No barometric pressure reading available; DO saturation "
            "computed assuming standard sea-level pressure (760 mmHg), "
            "which overestimates saturation at elevation."
        )

    return saturation, warnings


@register("oxygen_saturation")
class OxygenSaturationCalculator(BaseCalculator):
    """Computes percent dissolved-oxygen saturation."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="oxygen_saturation",
            display_name="Oxygen Saturation",
            formula_name="Benson-Krause (1984) DO solubility equation",
            reference=(
                "Benson, B.B. and Krause, D. Jr. (1984), Limnology and "
                "Oceanography, 29(3), 620-632; APHA Standard Methods "
                "4500-O G."
            ),
            output_unit="%",
            input_units={
                "dissolved_oxygen": "mg/L",
                "water_temperature": "C",
                "conductivity": "uS/cm",
                "barometric_pressure": "hPa",
            },
            required_inputs=("dissolved_oxygen", "water_temperature"),
            optional_inputs=_OPTIONAL_INPUTS,
            assumptions=_ASSUMPTIONS,
            limitations=_LIMITATIONS,
            valid_ranges={
                "dissolved_oxygen": (0.0, 20.0),
                "water_temperature": (0.0, 40.0),
            },
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute percent DO saturation.

        Args:
            inputs: Validated input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        saturation_concentration, warnings = _saturation_concentration_mg_l(inputs, config)
        measured_do = inputs["dissolved_oxygen"]
        percent_saturation = (measured_do / saturation_concentration) * 100.0
        confidence = 0.85 if not warnings else 0.6
        return percent_saturation, confidence, warnings


@register("oxygen_deficit")
class OxygenDeficitCalculator(BaseCalculator):
    """Computes the dissolved-oxygen deficit (saturation minus measured)."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="oxygen_deficit",
            display_name="Oxygen Deficit",
            formula_name="DO deficit = DO_saturation - DO_measured (Benson-Krause, 1984)",
            reference=(
                "Benson, B.B. and Krause, D. Jr. (1984), Limnology and "
                "Oceanography, 29(3), 620-632; standard oxygen-deficit "
                "definition used in stream reaeration models (e.g. "
                "Streeter-Phelps)."
            ),
            output_unit="mg/L",
            input_units={
                "dissolved_oxygen": "mg/L",
                "water_temperature": "C",
                "conductivity": "uS/cm",
                "barometric_pressure": "hPa",
            },
            required_inputs=("dissolved_oxygen", "water_temperature"),
            optional_inputs=_OPTIONAL_INPUTS,
            assumptions=_ASSUMPTIONS,
            limitations=_LIMITATIONS,
            valid_ranges={
                "dissolved_oxygen": (0.0, 20.0),
                "water_temperature": (0.0, 40.0),
            },
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute the DO deficit.

        Args:
            inputs: Validated input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        saturation_concentration, warnings = _saturation_concentration_mg_l(inputs, config)
        measured_do = inputs["dissolved_oxygen"]
        deficit = saturation_concentration - measured_do
        confidence = 0.85 if not warnings else 0.6
        return deficit, confidence, warnings
