"""Water-density derived-parameter calculator.

Contains:
    - :class:`WaterDensityCalculator` (registry key ``"water_density"``)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig


@register("water_density")
class WaterDensityCalculator(BaseCalculator):
    """Computes river water density from temperature (and optional salinity)."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="water_density",
            display_name="Water Density",
            formula_name="Kell (1975) pure-water density equation",
            reference=(
                "Kell, G.S. (1975), 'Density, thermal expansivity, and "
                "compressibility of liquid water from 0 to 150 C', Journal "
                "of Chemical and Engineering Data, 20(1), 97-105; "
                "dissolved-solids term linearized from Millero, F.J. and "
                "Poisson, A. (1981), Deep-Sea Research, 28A(6), 625-629."
            ),
            output_unit="kg/m^3",
            input_units={"water_temperature": "C", "conductivity": "uS/cm"},
            required_inputs=("water_temperature",),
            optional_inputs=("conductivity",),
            assumptions=(
                "Atmospheric pressure (Kell, 1975 is defined at 1 atm; no "
                "hydrostatic-pressure correction is applied for the "
                "shallow depths typical of river monitoring).",
                "When 'conductivity' is available, salinity is derived "
                "internally via PSS-78 and a linear dissolved-solids "
                "density correction is added if "
                "density.apply_salinity_correction is enabled in "
                "analytics.yaml; otherwise pure-water density is "
                "returned unmodified.",
            ),
            limitations=(
                "The salinity correction is linearized around low "
                "(river/estuarine) salinity and is not the full "
                "nonlinear UNESCO EOS-80 equation of state.",
                "Kell's equation is documented for 0-100 C at "
                "atmospheric pressure.",
            ),
            valid_ranges={"water_temperature": (0.0, 45.0)},
        )

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute water density from temperature (and optional salinity).

        Args:
            inputs: Validated input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        temperature = inputs["water_temperature"]
        density = equations.pure_water_density_kell_kg_m3(temperature)

        warnings: List[str] = []
        confidence = 0.9
        conductivity = inputs.get("conductivity")
        if conductivity is not None and config.density.apply_salinity_correction:
            salinity_psu = equations.practical_salinity_pss78(
                conductivity_us_cm=conductivity,
                temperature_c=temperature,
                reference_conductivity_us_cm=config.salinity.reference_conductivity_us_cm,
                pressure_dbar=config.salinity.reference_pressure_dbar,
            )
            density += equations.salinity_density_correction_kg_m3(
                salinity_psu=salinity_psu,
                coefficient_kg_m3_per_psu=config.density.salinity_expansion_coefficient_kg_m3_per_psu,
            )
        else:
            confidence = 0.75
            warnings.append(
                "No conductivity reading available; density computed for "
                "pure (zero-salinity) water."
            )

        return density, confidence, warnings
