"""Sediment-transport derived-parameter calculator.

Contains:
    - :class:`SedimentLoadCalculator` (registry key ``"sediment_load"``)

Supports two configurable methods (``sediment.method`` in
``analytics.yaml``):

    - ``"turbidity_surrogate"``: estimates suspended-sediment
      concentration (SSC) from turbidity, then combines it with
      discharge to estimate load (Rasmussen et al., 2009; Porterfield,
      1972).
    - ``"discharge_rating_curve"``: estimates sediment discharge
      directly from streamflow via a power-law rating curve
      (Asselman, 2000), without requiring a turbidity sensor.

Both methods need river discharge, which is computed internally using
the same hydraulic composition helper as
:mod:`app.analytics.hydrology` (imported, not duplicated).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata, NotComputableError
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig
from app.analytics.geometry import _DEPTH_INPUTS
from app.analytics.hydrology import _compute_velocity_and_area

_METHOD_TURBIDITY_SURROGATE = "turbidity_surrogate"
_METHOD_DISCHARGE_RATING_CURVE = "discharge_rating_curve"


@register("sediment_load")
class SedimentLoadCalculator(BaseCalculator):
    """Estimates suspended-sediment load using a configurable method."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="sediment_load",
            display_name="Estimated Sediment Load",
            formula_name=(
                "Turbidity-surrogate SSC-discharge load equation "
                "(Rasmussen et al., 2009; Porterfield, 1972) or "
                "discharge power-law sediment rating curve "
                "(Asselman, 2000), selected via analytics.yaml"
            ),
            reference=(
                "Rasmussen, P.P. et al. (2009), USGS Techniques and "
                "Methods, book 3, chap. C4; Porterfield, G. (1972), USGS "
                "TWRI Book 3, Chapter C3; Asselman, N.E.M. (2000), "
                "Journal of Hydrology, 234(3-4), 228-248."
            ),
            output_unit="tons/day",
            input_units={"turbidity": "NTU", "river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=("turbidity",) + _DEPTH_INPUTS,
            assumptions=(
                "River discharge is estimated internally using the same "
                "hydraulic model as the 'river_discharge' calculator "
                "(configured channel geometry, slope, and roughness).",
                "The turbidity-to-SSC and/or discharge-rating-curve "
                "coefficients (sediment.* in analytics.yaml) are fixed, "
                "site-calibrated regression constants.",
            ),
            limitations=(
                "Sediment rating curves and turbidity-SSC regressions are "
                "highly site- and event-specific; default coefficients "
                "are placeholders and MUST be calibrated against physical "
                "SSC samples before results are used for anything beyond "
                "rough screening.",
                "Does not account for bedload transport - suspended load "
                "only.",
            ),
            valid_ranges={"turbidity": (0.0, 4000.0)},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """Requirements depend on the configured method; handled in `_compute`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list - missing turbidity/depth/
            configuration is reported via :class:`NotComputableError`
            instead, since the requirement set depends on
            ``sediment.method``.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute estimated sediment load per the configured method.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If discharge cannot be computed, if
                turbidity is required but unavailable, or if
                ``sediment.method`` is not a recognized value.
        """
        sediment_config = config.sediment
        velocity, area, hydraulic_warnings = _compute_velocity_and_area(inputs, config)
        discharge_m3_s = equations.discharge(velocity_m_s=velocity, area_m2=area)
        warnings = list(hydraulic_warnings)

        if sediment_config.method == _METHOD_TURBIDITY_SURROGATE:
            turbidity = inputs.get("turbidity")
            if turbidity is None:
                raise NotComputableError(missing=["turbidity"])
            ssc = equations.suspended_sediment_concentration_from_turbidity(
                turbidity_ntu=turbidity,
                coefficient_a=sediment_config.turbidity_to_ssc_a,
                exponent_b=sediment_config.turbidity_to_ssc_b,
            )
            load = equations.sediment_load_from_concentration(
                ssc_mg_l=ssc,
                discharge_m3_s=discharge_m3_s,
                conversion_constant=sediment_config.load_conversion_constant,
            )
            confidence = 0.5
        elif sediment_config.method == _METHOD_DISCHARGE_RATING_CURVE:
            load = equations.sediment_rating_curve_load(
                discharge_m3_s=discharge_m3_s,
                coefficient_a=sediment_config.discharge_rating_curve_a,
                exponent_b=sediment_config.discharge_rating_curve_b,
            )
            confidence = 0.45
            warnings.append(
                "Sediment load estimated from a discharge rating curve "
                "only (no turbidity surrogate); accuracy depends heavily "
                "on site calibration."
            )
        else:
            raise NotComputableError(
                missing=[
                    f"a recognized sediment.method "
                    f"(got {sediment_config.method!r}; expected "
                    f"'turbidity_surrogate' or 'discharge_rating_curve')"
                ]
            )

        return load, confidence, warnings
