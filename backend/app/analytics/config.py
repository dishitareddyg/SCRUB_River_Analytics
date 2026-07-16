"""Analytics Engine configuration loader.

Loads every equation-selection flag, coefficient, and correction
factor used by the Analytics Engine from
``app/config/analytics.yaml``. No calculator module is permitted to
hardcode a numeric coefficient - all of them read from the typed
sections exposed here.

Mirrors the loading pattern used by
:mod:`app.serial.sensor_registry` (parse once, cache via
``lru_cache``, raise :class:`~app.utils.exceptions.ConfigurationError`
on anything malformed) so the two configuration subsystems behave
consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.utils.exceptions import ConfigurationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ANALYTICS_YAML_PATH = Path(__file__).resolve().parents[1] / "config" / "analytics.yaml"


@dataclass(frozen=True)
class TdsConfig:
    """Configuration for the TDS calculator.

    Attributes:
        conductivity_to_tds_factor: Empirical conductivity-to-TDS
            conversion factor (dimensionless).
    """

    conductivity_to_tds_factor: float


@dataclass(frozen=True)
class SalinityConfig:
    """Configuration for the salinity (PSS-78) calculator.

    Attributes:
        reference_conductivity_us_cm: Conductivity of standard
            seawater at 35 PSU, 15 C, 0 dbar, in uS/cm.
        reference_pressure_dbar: Reference gauge pressure, in dbar.
    """

    reference_conductivity_us_cm: float
    reference_pressure_dbar: float


@dataclass(frozen=True)
class OxygenSaturationConfig:
    """Configuration for the oxygen-saturation calculator.

    Attributes:
        standard_pressure_mmhg: Standard atmospheric pressure
            underlying the Benson-Krause saturation table, in mmHg.
        apply_salinity_correction: Whether to apply the Weiss/
            Benson-Krause salinity correction term.
        apply_pressure_correction: Whether to apply a barometric
            pressure (altitude) correction.
    """

    standard_pressure_mmhg: float
    apply_salinity_correction: bool
    apply_pressure_correction: bool


@dataclass(frozen=True)
class DensityConfig:
    """Configuration for the water-density calculator.

    Attributes:
        apply_salinity_correction: Whether to linearly correct the
            pure-water (Kell, 1975) density for dissolved solids.
        salinity_expansion_coefficient_kg_m3_per_psu: Linearized
            density correction coefficient, kg/m^3 per PSU.
    """

    apply_salinity_correction: bool
    salinity_expansion_coefficient_kg_m3_per_psu: float


@dataclass(frozen=True)
class GeometryConfig:
    """Configuration for the channel-geometry calculators.

    Attributes:
        channel_shape: Assumed cross-section shape (currently only
            ``"trapezoidal"`` is supported).
        bed_width_m: Surveyed channel bed width, in meters, or
            ``None`` if not yet configured for this site.
        side_slope_h_per_v: Surveyed trapezoidal side slope
            (horizontal run per unit vertical rise), or ``None`` if
            not yet configured for this site.
        sonar_profiler_available: Whether a sonar/multi-beam
            cross-section profiler is installed at this site.
    """

    channel_shape: str
    bed_width_m: Optional[float]
    side_slope_h_per_v: Optional[float]
    sonar_profiler_available: bool


@dataclass(frozen=True)
class HydraulicConfig:
    """Configuration for the flow-velocity and discharge calculators.

    Attributes:
        velocity_equation: Either ``"manning"`` or ``"chezy"``.
        channel_slope_m_per_m: Surveyed longitudinal channel bed
            slope (dimensionless, m/m), or ``None`` if not configured.
        manning_roughness_n: Manning's roughness coefficient
            (dimensionless).
        chezy_coefficient_c: Chezy resistance coefficient
            (m^(1/2)/s), or ``None`` if not configured.
    """

    velocity_equation: str
    channel_slope_m_per_m: Optional[float]
    manning_roughness_n: float
    chezy_coefficient_c: Optional[float]


@dataclass(frozen=True)
class SedimentConfig:
    """Configuration for the sediment-load calculator.

    Attributes:
        method: Either ``"turbidity_surrogate"`` or
            ``"discharge_rating_curve"``.
        turbidity_to_ssc_a: Power-law coefficient "a" for
            SSC = a * turbidity ^ b.
        turbidity_to_ssc_b: Power-law exponent "b" for
            SSC = a * turbidity ^ b.
        discharge_rating_curve_a: Power-law coefficient "a" for
            Qs = a * Q ^ b.
        discharge_rating_curve_b: Power-law exponent "b" for
            Qs = a * Q ^ b.
        load_conversion_constant: Constant converting
            SSC(mg/L) * Q(m^3/s) into metric tons/day.
    """

    method: str
    turbidity_to_ssc_a: float
    turbidity_to_ssc_b: float
    discharge_rating_curve_a: float
    discharge_rating_curve_b: float
    load_conversion_constant: float


@dataclass(frozen=True)
class AnalyticsConfig:
    """Top-level, immutable Analytics Engine configuration.

    Attributes:
        tds: TDS calculator configuration.
        salinity: Salinity calculator configuration.
        oxygen_saturation: Oxygen-saturation calculator configuration.
        density: Water-density calculator configuration.
        geometry: Channel-geometry calculator configuration.
        hydraulic: Flow-velocity/discharge calculator configuration.
        sediment: Sediment-load calculator configuration.
    """

    tds: TdsConfig
    salinity: SalinityConfig
    oxygen_saturation: OxygenSaturationConfig
    density: DensityConfig
    geometry: GeometryConfig
    hydraulic: HydraulicConfig
    sediment: SedimentConfig


def _require(section: Dict[str, Any], key: str, path: Path, section_name: str) -> Any:
    """Fetch a required key from a config section, raising if absent.

    Args:
        section: The parsed section dict.
        key: The required key name.
        path: The YAML file path (for error messages).
        section_name: The section name (for error messages).

    Returns:
        The value stored at ``key``.

    Raises:
        ConfigurationError: If ``key`` is missing from ``section``.
    """
    if key not in section:
        raise ConfigurationError(
            f"Missing required key '{section_name}.{key}' in {path}"
        )
    return section[key]


def load_analytics_config(yaml_path: Path = _ANALYTICS_YAML_PATH) -> AnalyticsConfig:
    """Parse ``analytics.yaml`` into a typed :class:`AnalyticsConfig`.

    Args:
        yaml_path: Path to the ``analytics.yaml`` configuration file.

    Returns:
        A populated, immutable :class:`AnalyticsConfig`.

    Raises:
        ConfigurationError: If the file is missing, malformed, or
            missing required keys.
    """
    if not yaml_path.exists():
        raise ConfigurationError(f"Analytics configuration file not found: {yaml_path}")

    try:
        with yaml_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Failed to parse analytics configuration: {exc}") from exc

    try:
        wq = raw["water_quality"]
        tds_section = wq["tds"]
        salinity_section = wq["salinity"]
        oxygen_section = raw["oxygen"]["saturation"]
        density_section = raw["density"]
        geometry_section = raw["geometry"]
        hydraulic_section = raw["hydraulic"]
        sediment_section = raw["sediment"]

        config = AnalyticsConfig(
            tds=TdsConfig(
                conductivity_to_tds_factor=float(
                    _require(tds_section, "conductivity_to_tds_factor", yaml_path, "water_quality.tds")
                ),
            ),
            salinity=SalinityConfig(
                reference_conductivity_us_cm=float(
                    _require(
                        salinity_section,
                        "reference_conductivity_us_cm",
                        yaml_path,
                        "water_quality.salinity",
                    )
                ),
                reference_pressure_dbar=float(salinity_section.get("reference_pressure_dbar", 0.0)),
            ),
            oxygen_saturation=OxygenSaturationConfig(
                standard_pressure_mmhg=float(
                    _require(oxygen_section, "standard_pressure_mmhg", yaml_path, "oxygen.saturation")
                ),
                apply_salinity_correction=bool(oxygen_section.get("apply_salinity_correction", True)),
                apply_pressure_correction=bool(oxygen_section.get("apply_pressure_correction", True)),
            ),
            density=DensityConfig(
                apply_salinity_correction=bool(density_section.get("apply_salinity_correction", True)),
                salinity_expansion_coefficient_kg_m3_per_psu=float(
                    _require(
                        density_section,
                        "salinity_expansion_coefficient_kg_m3_per_psu",
                        yaml_path,
                        "density",
                    )
                ),
            ),
            geometry=GeometryConfig(
                channel_shape=str(geometry_section.get("channel_shape", "trapezoidal")),
                bed_width_m=_optional_float(geometry_section.get("bed_width_m")),
                side_slope_h_per_v=_optional_float(geometry_section.get("side_slope_h_per_v")),
                sonar_profiler_available=bool(geometry_section.get("sonar_profiler_available", False)),
            ),
            hydraulic=HydraulicConfig(
                velocity_equation=str(hydraulic_section.get("velocity_equation", "manning")).lower(),
                channel_slope_m_per_m=_optional_float(hydraulic_section.get("channel_slope_m_per_m")),
                manning_roughness_n=float(hydraulic_section.get("manning_roughness_n", 0.035)),
                chezy_coefficient_c=_optional_float(hydraulic_section.get("chezy_coefficient_c")),
            ),
            sediment=SedimentConfig(
                method=str(sediment_section.get("method", "turbidity_surrogate")),
                turbidity_to_ssc_a=float(sediment_section.get("turbidity_to_ssc_a", 1.0)),
                turbidity_to_ssc_b=float(sediment_section.get("turbidity_to_ssc_b", 1.0)),
                discharge_rating_curve_a=float(sediment_section.get("discharge_rating_curve_a", 0.01)),
                discharge_rating_curve_b=float(sediment_section.get("discharge_rating_curve_b", 1.5)),
                load_conversion_constant=float(
                    sediment_section.get("load_conversion_constant", 0.0864)
                ),
            ),
        )
    except KeyError as exc:
        raise ConfigurationError(f"Invalid analytics.yaml: missing section {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid analytics.yaml value: {exc}") from exc

    logger.info(f"Loaded Analytics Engine configuration from {yaml_path}")
    return config


def _optional_float(value: Any) -> Optional[float]:
    """Coerce a possibly-``None`` YAML value into an optional float.

    Args:
        value: The raw YAML value (may be ``None``).

    Returns:
        ``None`` if ``value`` is ``None``, otherwise ``float(value)``.
    """
    return None if value is None else float(value)


@lru_cache
def get_analytics_config() -> AnalyticsConfig:
    """Return a cached, process-wide :class:`AnalyticsConfig` instance.

    Returns:
        The singleton :class:`AnalyticsConfig`.
    """
    return load_analytics_config()
