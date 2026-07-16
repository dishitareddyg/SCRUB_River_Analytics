"""Open-channel geometry derived-parameter calculators.

All five geometry calculators here share the same trapezoidal-channel
approximation (Chow, 1959) and the same two site-survey configuration
values (``geometry.bed_width_m`` and ``geometry.side_slope_h_per_v``
in ``analytics.yaml``), which are NOT sensor readings but must be
calibrated per deployment site. When either is left unconfigured
(``null``), every calculator here reports
:attr:`~app.analytics.result.CalculationStatus.NOT_COMPUTABLE`, per
the module requirement that river width (and everything derived from
it) return "Not Computable" when insufficient inputs/configuration
are available, rather than silently guessing a channel shape.

Depth is resolved from whichever of ``river_depth`` or ``water_level``
is available (in that preference order), since either sensor can
serve as the flow depth at the monitoring cross-section.

Contains:
    - :class:`RiverWidthCalculator` (registry key ``"river_width"``)
    - :class:`CrossSectionalAreaCalculator` (registry key ``"cross_sectional_area"``)
    - :class:`WettedPerimeterCalculator` (registry key ``"wetted_perimeter"``)
    - :class:`HydraulicRadiusCalculator` (registry key ``"hydraulic_radius"``)
    - :class:`HydraulicDepthCalculator` (registry key ``"hydraulic_depth"``)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.analytics import equations
from app.analytics.base import BaseCalculator, CalculatorMetadata, NotComputableError
from app.analytics.calculator_registry import register
from app.analytics.config import AnalyticsConfig, GeometryConfig

_DEPTH_INPUTS: Tuple[str, ...] = ("river_depth", "water_level")

_GEOMETRY_ASSUMPTIONS: Tuple[str, ...] = (
    "The channel cross-section is approximated as a trapezoid "
    "(geometry.channel_shape in analytics.yaml), defined by a fixed "
    "site-surveyed bed width and side slope.",
    "Flow depth is taken from 'river_depth' when available, falling "
    "back to 'water_level' otherwise.",
)

_GEOMETRY_LIMITATIONS: Tuple[str, ...] = (
    "A trapezoidal approximation cannot capture irregular natural "
    "channel cross-sections; accuracy depends entirely on how well "
    "the configured bed width/side slope represent the true "
    "cross-section at the monitoring point.",
    "bed_width_m and side_slope_h_per_v are static site-survey "
    "values in analytics.yaml, not live sensor readings - they must "
    "be re-surveyed and reconfigured if the channel geometry changes "
    "(e.g. after a flood event).",
)


def _resolve_depth(inputs: Dict[str, Optional[float]]) -> float:
    """Resolve flow depth from whichever depth sensor is available.

    Args:
        inputs: The full input mapping.

    Returns:
        The resolved depth, in meters.

    Raises:
        NotComputableError: If neither 'river_depth' nor
            'water_level' is available.
    """
    for name in _DEPTH_INPUTS:
        value = inputs.get(name)
        if value is not None:
            return value
    raise NotComputableError(missing=list(_DEPTH_INPUTS))


def _resolve_geometry(config: AnalyticsConfig) -> GeometryConfig:
    """Fetch and validate the site-survey geometry configuration.

    Args:
        config: The active analytics configuration.

    Returns:
        The validated :class:`~app.analytics.config.GeometryConfig`.

    Raises:
        NotComputableError: If ``bed_width_m`` or
            ``side_slope_h_per_v`` has not been configured for this
            site.
    """
    geometry = config.geometry
    missing = []
    if geometry.bed_width_m is None:
        missing.append("geometry.bed_width_m (site survey configuration)")
    if geometry.side_slope_h_per_v is None:
        missing.append("geometry.side_slope_h_per_v (site survey configuration)")
    if missing:
        raise NotComputableError(missing=missing)
    return geometry


@register("river_width")
class RiverWidthCalculator(BaseCalculator):
    """Estimates river (top/water-surface) width from depth and channel geometry."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="river_width",
            display_name="River Width",
            formula_name="Trapezoidal channel top width (Chow, 1959)",
            reference=(
                "Chow, V.T. (1959), 'Open-Channel Hydraulics', "
                "McGraw-Hill, Chapter 2, Table 2-1."
            ),
            output_unit="m",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_GEOMETRY_ASSUMPTIONS,
            limitations=_GEOMETRY_LIMITATIONS
            + (
                "Returns NOT_COMPUTABLE when no sonar/multi-beam cross-"
                "section profiler is configured and the trapezoidal "
                "site-survey geometry (bed width, side slope) is also "
                "unconfigured - width cannot be estimated from a single "
                "depth reading alone without one of these.",
            ),
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """Depth may come from either of two sensors; handled in `_compute`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list - depth-resolution failure is
            reported via :class:`NotComputableError` from
            :meth:`_compute` instead, since it is an "any of"
            requirement rather than an "all of" requirement.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute river width from depth and configured channel geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If depth or site-survey geometry is
                unavailable.
        """
        depth = _resolve_depth(inputs)
        geometry = _resolve_geometry(config)
        width = equations.trapezoidal_top_width(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        confidence = 0.6 if not geometry.sonar_profiler_available else 0.75
        warnings: List[str] = []
        if not geometry.sonar_profiler_available:
            warnings.append(
                "No sonar/multi-beam cross-section profiler configured for "
                "this site; width is a trapezoidal approximation only."
            )
        return width, confidence, warnings


@register("cross_sectional_area")
class CrossSectionalAreaCalculator(BaseCalculator):
    """Estimates channel cross-sectional flow area."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="cross_sectional_area",
            display_name="Cross-Sectional Area",
            formula_name="Trapezoidal channel area (Chow, 1959)",
            reference=(
                "Chow, V.T. (1959), 'Open-Channel Hydraulics', "
                "McGraw-Hill, Chapter 2, Table 2-1."
            ),
            output_unit="m^2",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_GEOMETRY_ASSUMPTIONS,
            limitations=_GEOMETRY_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """See :meth:`RiverWidthCalculator.validate_inputs`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute cross-sectional area from depth and channel geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If depth or site-survey geometry is
                unavailable.
        """
        depth = _resolve_depth(inputs)
        geometry = _resolve_geometry(config)
        area = equations.trapezoidal_cross_sectional_area(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        return area, 0.75, []


@register("wetted_perimeter")
class WettedPerimeterCalculator(BaseCalculator):
    """Estimates channel wetted perimeter."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="wetted_perimeter",
            display_name="Wetted Perimeter",
            formula_name="Trapezoidal channel wetted perimeter (Chow, 1959)",
            reference=(
                "Chow, V.T. (1959), 'Open-Channel Hydraulics', "
                "McGraw-Hill, Chapter 2, Table 2-1."
            ),
            output_unit="m",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_GEOMETRY_ASSUMPTIONS,
            limitations=_GEOMETRY_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """See :meth:`RiverWidthCalculator.validate_inputs`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute wetted perimeter from depth and channel geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If depth or site-survey geometry is
                unavailable.
        """
        depth = _resolve_depth(inputs)
        geometry = _resolve_geometry(config)
        perimeter = equations.trapezoidal_wetted_perimeter(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        return perimeter, 0.75, []


@register("hydraulic_radius")
class HydraulicRadiusCalculator(BaseCalculator):
    """Estimates hydraulic radius (area / wetted perimeter)."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="hydraulic_radius",
            display_name="Hydraulic Radius",
            formula_name="R = A / P (Chow, 1959)",
            reference="Chow, V.T. (1959), 'Open-Channel Hydraulics', McGraw-Hill, Chapter 2.",
            output_unit="m",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_GEOMETRY_ASSUMPTIONS,
            limitations=_GEOMETRY_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """See :meth:`RiverWidthCalculator.validate_inputs`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute hydraulic radius from depth and channel geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If depth or site-survey geometry is
                unavailable, or if the resulting wetted perimeter is
                zero.
        """
        depth = _resolve_depth(inputs)
        geometry = _resolve_geometry(config)
        area = equations.trapezoidal_cross_sectional_area(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        perimeter = equations.trapezoidal_wetted_perimeter(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        if perimeter == 0:
            raise NotComputableError(missing=["non-zero wetted perimeter (depth is zero)"])
        radius = equations.hydraulic_radius(area_m2=area, wetted_perimeter_m=perimeter)
        return radius, 0.75, []


@register("hydraulic_depth")
class HydraulicDepthCalculator(BaseCalculator):
    """Estimates hydraulic (mean) depth (area / top width)."""

    def metadata(self) -> CalculatorMetadata:
        """Return this calculator's descriptive metadata.

        Returns:
            The :class:`CalculatorMetadata` describing this
            calculator's formula, inputs, and assumptions.
        """
        return CalculatorMetadata(
            key="hydraulic_depth",
            display_name="Hydraulic Depth",
            formula_name="D = A / T (Chow, 1959)",
            reference="Chow, V.T. (1959), 'Open-Channel Hydraulics', McGraw-Hill, Chapter 2.",
            output_unit="m",
            input_units={"river_depth": "m", "water_level": "m"},
            required_inputs=(),
            optional_inputs=_DEPTH_INPUTS,
            assumptions=_GEOMETRY_ASSUMPTIONS,
            limitations=_GEOMETRY_LIMITATIONS,
            valid_ranges={},
        )

    def validate_inputs(self, inputs: Dict[str, Optional[float]]) -> List[str]:
        """See :meth:`RiverWidthCalculator.validate_inputs`.

        Args:
            inputs: The input mapping.

        Returns:
            Always an empty list.
        """
        return []

    def _compute(
        self, inputs: Dict[str, Optional[float]], config: AnalyticsConfig
    ) -> Tuple[float, float, List[str]]:
        """Compute hydraulic depth from depth and channel geometry.

        Args:
            inputs: Input mapping.
            config: The active analytics configuration.

        Returns:
            A ``(value, confidence, warnings)`` tuple.

        Raises:
            NotComputableError: If depth or site-survey geometry is
                unavailable, or if the resulting top width is zero.
        """
        depth = _resolve_depth(inputs)
        geometry = _resolve_geometry(config)
        area = equations.trapezoidal_cross_sectional_area(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        top_width = equations.trapezoidal_top_width(
            depth_m=depth, bed_width_m=geometry.bed_width_m, side_slope_h_per_v=geometry.side_slope_h_per_v
        )
        if top_width == 0:
            raise NotComputableError(missing=["non-zero top width (depth is zero)"])
        hydraulic_depth_value = equations.hydraulic_depth(area_m2=area, top_width_m=top_width)
        return hydraulic_depth_value, 0.75, []
