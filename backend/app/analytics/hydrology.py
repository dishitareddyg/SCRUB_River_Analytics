"""Open-channel hydraulic flow derived-parameter calculators.

Contains:
    - :class:`FlowVelocityCalculator` (registry key ``"flow_velocity"``)
    - :class:`RiverDischargeCalculator` (registry key ``"river_discharge"``)

Both build on the same trapezoidal-geometry helpers used by
:mod:`app.analytics.geometry` (imported, not duplicated) plus the
site-surveyed channel slope and a configurable choice of hydraulic
equation (Manning or Chezy), per ``hydraulic.velocity_equation`` in
``analytics.yaml``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata, NotComputableError
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig
from app.analytics.geometry import _DEPTH_INPUTS, _resolve_depth, _resolve_geometry

_HYDRAULIC_ASSUMPTIONS: Tuple[str, ...] = (
    "Channel geometry is the same trapezoidal approximation used by "
    "the geometry calculators (geometry.bed_width_m, "
    "geometry.side_slope_h_per_v in analytics.yaml).",
    "The channel bed (energy) slope and roughness/resistance "
    "coefficient are fixed, site-surveyed configuration values "
    "(hydraulic.channel_slope_m_per_m and either "
    "hydraulic.manning_roughness_n or hydraulic.chezy_coefficient_c), "
    "not live sensor readings.",
    "Uniform (steady, normal) flow is assumed, as required by both "
    "the Manning and Chezy equations.",
)

_HYDRAULIC_LIMITATIONS: Tuple[str, ...] = (
    "Manning's n / Chezy's C are empirical roughness values that vary "
    "with stage, vegetation, and bed material; the configured constant "
    "is a site-average approximation.",
    "Neither equation accounts for unsteady or non-uniform flow "
    "(e.g. rapidly changing stage during a flood peak).",
)


def _resolve_channel_slope(config: AnalyticsConfig) -> float:
    """Fetch and validate the site-surveyed channel slope.

    Args:
        config: The active analytics configuration.

    Returns:
        The configured channel slope, dimensionless (m/m).

    Raises:
        NotComputableError: If ``hydraulic.channel_slope_m_per_m`` has
            not been configured for this site.
    """
    slope = config.hydraulic.channel_slope_m_per_m
    if slope is None:
        raise NotComputableError(missing=["hydraulic.channel_slope_m_per_m (site survey configuration)"])
    return slope


def _compute_velocity_and_area(
    inputs: Dict[str, Optional[float]], config: AnalyticsConfig
) -> Tuple[float, float, List[str]]:
    """Compute flow velocity and cross-sectional area for this site/reading.

    Shared by :class:`FlowVelocityCalculator` and
    :class:`RiverDischargeCalculator` so the velocity equation is
    implemented exactly once.

    Args:
        inputs: Input mapping (depth resolved via
            :func:`app.analytics.geometry._resolve_depth`).
        config: The active analytics configuration.

    Returns:
        A ``(velocity_m_s, area_m2, warnings)`` tuple.

    Raises:
        NotComputableError: If depth, channel geometry, channel
            slope, or the selected equation's resistance coefficient
            is unavailable, or if ``hydraulic.velocity_equation`` is
            not a recognized value.
    """
    depth = _resolve_depth(inputs)
    geometry = _resolve_geometry(config)
    slope = _resolve_channel_slope(config)

    area = equations.trapezoidal_cross_sectional_area(
        depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
    )
    perimeter = equations.trapezoidal_wetted_perimeter(
        depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
    )
    if perimeter == 0:
        raise NotComputableError(missing=["non-zero wetted perimeter (depth is zero)"])
    radius = equations.hydraulic_radius(area_m2=area, wetted_perimeter_m=perimeter)

    equation_choice = config.hydraulic.velocity_equation
    warnings: List[str] = []

    if equation_choice == "manning":
        velocity = equations.manning_velocity(
            hydraulic_radius_m=radius,
            slope_m_per_m=slope,
            roughness_n=config.hydraulic.manning_roughness_n,
        )
    elif equation_choice == "chezy":
        chezy_c = config.hydraulic.chezy_coefficient_c
        if chezy_c is None:
            raise NotComputableError(
                missing=["hydraulic.chezy_coefficient_c (site survey configuration)"]
            )
        velocity = equations.chezy_velocity(
            hydraulic_radius_m=radius, slope_m_per_m=slope, chezy_c=chezy_c
        )
    else:
        raise NotComputableError(
            missing=[
                f"a recognized hydraulic.velocity_equation "
                f"(got {equation_choice!r}; expected 'manning' or 'chezy')"
            ]
        )

    return velocity, area, warnings


@register("flow_velocity")
class FlowVelocityCalculator(BaseCalculator):
    """Estimates mean cross-sectional flow velocity via a configurable equation."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="flow_velocity",
            display_name="Estimated Flow Velocity",
            formula_name=(
                "Manning's equation (Manning, 1891) or Chezy's equation "
                "(Chezy, 1775), selected via analytics.yaml"
            ),
            reference=(
                "Chow, V.T. (1959), 'Open-Channel Hydraulics', "
                "McGraw-Hill, Chapters 7-8."
            ),
            output_unit="m/s",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_HYDRAULIC_ASSUMPTIONS,
            limitations=_HYDRAULIC_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """Depth may come from either of two sensors; handled in `_compute`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list - missing depth/configuration is
            reported via :class:`NotComputableError` instead.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute flow velocity for the configured equation and site geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        velocity, _area, warnings = _compute_velocity_and_area(inputs, config)
        return velocity, 0.65, warnings


@register("river_discharge")
class RiverDischargeCalculator(BaseCalculator):
    """Estimates volumetric river discharge via the continuity equation."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="river_discharge",
            display_name="River Discharge",
            formula_name="Continuity equation: Q = V * A (Chow, 1959)",
            reference=(
                "Chow, V.T. (1959), 'Open-Channel Hydraulics', "
                "McGraw-Hill, Chapter 1."
            ),
            output_unit="m^3/s",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_HYDRAULIC_ASSUMPTIONS
            + ("Velocity is estimated (not directly measured) via the "
               "configured Manning/Chezy equation.",),
            limitations=_HYDRAULIC_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """Depth may come from either of two sensors; handled in `_compute`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list - missing depth/configuration is
            reported via :class:`NotComputableError` instead.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute river discharge for the configured equation and site geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.
        """
        velocity, area, warnings = _compute_velocity_and_area(inputs, config)
        q = equations.discharge(velocity_m_s=velocity, area_m2=area)
        return q, 0.6, warnings
