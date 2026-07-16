"""Published engineering and scientific equations.

Every function in this module implements one specific, citable
formula, in isolation from any I/O, configuration parsing, or
:class:`~app.analytics.result.CalculationResult` construction - those
concerns live in the calculator classes (``water_quality.py``,
``oxygen.py``, ``geometry.py``, ``hydrology.py``, ``density.py``,
``sediment.py``) that call these functions. Keeping the math here,
separated from orchestration, is what lets every calculator share a
single implementation of each formula (no duplicated equations).

Units are documented explicitly on every function since mixing units
silently is the single easiest way to corrupt hydrology data.
"""

from __future__ import annotations

import math
from typing import Optional


# =============================================================================
# Water quality
# =============================================================================


def conductivity_to_tds(conductivity_us_cm: float, conversion_factor: float) -> float:
    """Estimate Total Dissolved Solids from electrical conductivity.

    Formula: TDS (mg/L) = conversion_factor * EC (uS/cm)

    Reference:
        Hem, J.D. (1985), "Study and Interpretation of the Chemical
        Characteristics of Natural Water", USGS Water-Supply Paper
        2254, 3rd ed., p. 66.

    Args:
        conductivity_us_cm: Electrical conductivity, in uS/cm.
        conversion_factor: Empirical conversion factor (dimensionless,
            typically 0.55-0.75 for natural waters).

    Returns:
        Estimated TDS, in mg/L.
    """
    return conversion_factor * conductivity_us_cm


def practical_salinity_pss78(
    conductivity_us_cm: float,
    temperature_c: float,
    reference_conductivity_us_cm: float,
    pressure_dbar: float = 0.0,
) -> float:
    """Compute Practical Salinity per the Practical Salinity Scale 1978.

    Formula: PSS-78, as defined by the polynomial::

        S = a0 + a1*R^0.5 + a2*R + a3*R^1.5 + a4*R^2 + a5*R^2.5 + dS

        dS = [(T-15)/(1+0.0162*(T-15))] *
             (b0 + b1*R^0.5 + b2*R + b3*R^1.5 + b4*R^2 + b5*R^2.5)

    where ``R`` is the conductivity ratio of the sample to standard
    seawater (35 PSU, 15 C, 0 dbar), temperature-corrected via the
    ``rt(T)`` polynomial before use.

    Reference:
        Fofonoff, N.P. and Millard, R.C. Jr. (1983), "Algorithms for
        computation of fundamental properties of seawater", UNESCO
        Technical Papers in Marine Science No. 44.

    Args:
        conductivity_us_cm: Sample electrical conductivity, in uS/cm.
        temperature_c: Sample temperature, in degrees Celsius.
        reference_conductivity_us_cm: Conductivity of standard
            seawater at 35 PSU, 15 C, 0 dbar, in uS/cm
            (approximately 42914.0).
        pressure_dbar: Gauge pressure at the sample, in dbar.
            Defaults to 0.0 (surface). Included for interface
            completeness; the pressure correction term (Fofonoff &
            Millard, 1983) is a small, higher-order effect and is not
            applied for shallow river deployments.

    Returns:
        Practical salinity, in PSU (practical salinity units,
        dimensionless, numerically equivalent to ppt).

    Note:
        PSS-78 is formally defined and validated for the oceanic
        salinity range of 2-42 PSU. For freshwater rivers (salinity
        well below 2 PSU) this remains the standard, published
        conductivity-to-salinity relationship, but accuracy degrades
        toward the low end of the scale - see the calculator's
        ``limitations`` metadata.
    """
    del pressure_dbar  # Reserved for a future pressure-correction term.

    # rt(T): the conductivity ratio of seawater at temperature T,
    # pressure 0, relative to seawater at 15 C, pressure 0 (Fofonoff &
    # Millard, 1983, eq. 3).
    c0, c1, c2, c3, c4 = 0.6766097, 2.00564e-2, 1.104259e-4, -6.9698e-7, 1.0031e-9
    rt = c0 + c1 * temperature_c + c2 * temperature_c**2 + c3 * temperature_c**3 + c4 * temperature_c**4

    rt_ratio = conductivity_us_cm / reference_conductivity_us_cm
    r_value = rt_ratio / rt if rt != 0 else 0.0
    r_value = max(r_value, 0.0)
    sqrt_r = math.sqrt(r_value)

    a0, a1, a2, a3, a4, a5 = 0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081
    b0, b1, b2, b3, b4, b5 = 0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144

    salinity_base = (
        a0
        + a1 * sqrt_r
        + a2 * r_value
        + a3 * r_value**1.5
        + a4 * r_value**2
        + a5 * r_value**2.5
    )
    salinity_temp_term = (
        b0
        + b1 * sqrt_r
        + b2 * r_value
        + b3 * r_value**1.5
        + b4 * r_value**2
        + b5 * r_value**2.5
    )
    delta_s = ((temperature_c - 15.0) / (1.0 + 0.0162 * (temperature_c - 15.0))) * salinity_temp_term

    return salinity_base + delta_s


# =============================================================================
# Dissolved oxygen
# =============================================================================


def oxygen_saturation_concentration_mg_l(temperature_c: float) -> float:
    """Dissolved-oxygen saturation concentration at standard pressure.

    Formula: Benson-Krause equation, in the form adopted by APHA
    Standard Methods and the USGS::

        ln(DO_sat) = -139.34411
                      + 1.575701e5 / T_K
                      - 6.642308e7 / T_K^2
                      + 1.243800e10 / T_K^3
                      - 8.621949e11 / T_K^4

    Valid for freshwater (0 salinity) at standard atmospheric
    pressure (760 mmHg).

    Reference:
        Benson, B.B. and Krause, D. Jr. (1984), "The concentration
        and isotopic fractionation of oxygen dissolved in freshwater
        and seawater in equilibrium with the atmosphere", Limnology
        and Oceanography, 29(3), 620-632; as codified in APHA
        Standard Methods for the Examination of Water and Wastewater,
        23rd ed., Method 4500-O G.

    Args:
        temperature_c: Water temperature, in degrees Celsius.
            Documented valid range: 0-40 C.

    Returns:
        Dissolved-oxygen saturation concentration, in mg/L, at
        standard pressure and zero salinity.
    """
    t_kelvin = temperature_c + 273.15
    ln_do = (
        -139.34411
        + (1.575701e5 / t_kelvin)
        - (6.642308e7 / t_kelvin**2)
        + (1.2438e10 / t_kelvin**3)
        - (8.621949e11 / t_kelvin**4)
    )
    return math.exp(ln_do)


def oxygen_salinity_correction_factor(salinity_psu: float, temperature_c: float) -> float:
    """Multiplicative salinity correction for DO saturation concentration.

    Formula: Weiss (1970) / Benson-Krause (1984) salinity term::

        ln(DO_sat_S / DO_sat_0) = -Salinity *
            (0.017674 - 10.754/T_K + 2140.7/T_K^2)

    Reference:
        Weiss, R.F. (1970), "The solubility of nitrogen, oxygen and
        argon in water and seawater", Deep-Sea Research, 17(4),
        721-735, as adapted by Benson, B.B. and Krause, D. Jr. (1984)
        and adopted in APHA Standard Methods 4500-O G.

    Args:
        salinity_psu: Water salinity, in PSU (practical salinity
            units, ~ppt).
        temperature_c: Water temperature, in degrees Celsius.

    Returns:
        A multiplicative correction factor to apply to the
        zero-salinity DO saturation concentration
        (dimensionless, <= 1.0 for salinity > 0).
    """
    t_kelvin = temperature_c + 273.15
    ln_correction = -salinity_psu * (0.017674 - 10.754 / t_kelvin + 2140.7 / t_kelvin**2)
    return math.exp(ln_correction)


def oxygen_pressure_correction_factor(
    barometric_pressure_hpa: float, standard_pressure_mmhg: float
) -> float:
    """Barometric-pressure (altitude) correction for DO saturation concentration.

    Formula: linear barometric-pressure ratio correction::

        correction_factor = BP(mmHg) / standard_pressure_mmHg

    This is the simplified, widely used engineering approximation of
    the full APHA Standard Methods 4500-O G barometric correction
    (which additionally accounts for the vapor pressure of water at
    the sample temperature - a second-order effect at typical river
    monitoring altitudes).

    Reference:
        APHA, AWWA, WEF (2017), "Standard Methods for the Examination
        of Water and Wastewater", 23rd ed., Method 4500-O G.

    Args:
        barometric_pressure_hpa: Measured barometric pressure, in
            hPa (millibars).
        standard_pressure_mmhg: The standard pressure the saturation
            table was defined at, in mmHg (typically 760.0).

    Returns:
        A multiplicative correction factor (dimensionless).
    """
    barometric_pressure_mmhg = barometric_pressure_hpa * 0.750062
    return barometric_pressure_mmhg / standard_pressure_mmhg


# =============================================================================
# Density
# =============================================================================


def pure_water_density_kell_kg_m3(temperature_c: float) -> float:
    """Density of pure water as a function of temperature.

    Formula: Kell (1975) equation::

        rho(T) = (999.83952 + 16.945176*T - 7.9870401e-3*T^2
                  - 46.170461e-6*T^3 + 105.56302e-9*T^4
                  - 280.54253e-12*T^5) / (1 + 16.879850e-3*T)

    Reference:
        Kell, G.S. (1975), "Density, thermal expansivity, and
        compressibility of liquid water from 0 to 150 C: correlations
        and tables for atmospheric pressure and saturation reviewed
        and expressed on 1968 temperature scale", Journal of Chemical
        and Engineering Data, 20(1), 97-105.

    Args:
        temperature_c: Water temperature, in degrees Celsius.
            Documented valid range: 0-100 C (atmospheric pressure).

    Returns:
        Pure-water density, in kg/m^3.
    """
    numerator = (
        999.83952
        + 16.945176 * temperature_c
        - 7.9870401e-3 * temperature_c**2
        - 46.170461e-6 * temperature_c**3
        + 105.56302e-9 * temperature_c**4
        - 280.54253e-12 * temperature_c**5
    )
    denominator = 1.0 + 16.879850e-3 * temperature_c
    return numerator / denominator


def salinity_density_correction_kg_m3(
    salinity_psu: float, coefficient_kg_m3_per_psu: float
) -> float:
    """Linearized dissolved-solids correction to freshwater density.

    Formula: rho_correction = coefficient * Salinity

    This linearizes the salinity term of the UNESCO EOS-80 equation
    of state around low (river/estuarine) salinity, where the
    nonlinear terms are negligible.

    Reference:
        Millero, F.J. and Poisson, A. (1981), "International
        one-atmosphere equation of state of seawater", Deep-Sea
        Research, 28A(6), 625-629.

    Args:
        salinity_psu: Water salinity, in PSU.
        coefficient_kg_m3_per_psu: Linearized density-increase
            coefficient, in kg/m^3 per PSU.

    Returns:
        The density correction to add to the pure-water density, in
        kg/m^3.
    """
    return coefficient_kg_m3_per_psu * salinity_psu


# =============================================================================
# Open-channel geometry (trapezoidal channel approximation)
# =============================================================================


def trapezoidal_top_width(depth_m: float, bed_width_m: float, side_slope_h_per_v: float) -> float:
    """Water-surface (top) width of a trapezoidal channel.

    Formula: T = b + 2*z*h

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 2, Table 2-1.

    Args:
        depth_m: Flow depth, in meters.
        bed_width_m: Channel bed (bottom) width, in meters.
        side_slope_h_per_v: Side slope, horizontal run per unit
            vertical rise (dimensionless).

    Returns:
        Top (water-surface) width, in meters.
    """
    return bed_width_m + 2.0 * side_slope_h_per_v * depth_m


def trapezoidal_cross_sectional_area(
    depth_m: float, bed_width_m: float, side_slope_h_per_v: float
) -> float:
    """Cross-sectional flow area of a trapezoidal channel.

    Formula: A = (b + z*h) * h

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 2, Table 2-1.

    Args:
        depth_m: Flow depth, in meters.
        bed_width_m: Channel bed (bottom) width, in meters.
        side_slope_h_per_v: Side slope, horizontal run per unit
            vertical rise (dimensionless).

    Returns:
        Cross-sectional flow area, in m^2.
    """
    return (bed_width_m + side_slope_h_per_v * depth_m) * depth_m


def trapezoidal_wetted_perimeter(
    depth_m: float, bed_width_m: float, side_slope_h_per_v: float
) -> float:
    """Wetted perimeter of a trapezoidal channel.

    Formula: P = b + 2*h*sqrt(1 + z^2)

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 2, Table 2-1.

    Args:
        depth_m: Flow depth, in meters.
        bed_width_m: Channel bed (bottom) width, in meters.
        side_slope_h_per_v: Side slope, horizontal run per unit
            vertical rise (dimensionless).

    Returns:
        Wetted perimeter, in meters.
    """
    return bed_width_m + 2.0 * depth_m * math.sqrt(1.0 + side_slope_h_per_v**2)


def hydraulic_radius(area_m2: float, wetted_perimeter_m: float) -> float:
    """Hydraulic radius of a channel cross-section.

    Formula: R = A / P

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 2.

    Args:
        area_m2: Cross-sectional flow area, in m^2.
        wetted_perimeter_m: Wetted perimeter, in meters.

    Returns:
        Hydraulic radius, in meters.

    Raises:
        ZeroDivisionError: If ``wetted_perimeter_m`` is zero.
    """
    return area_m2 / wetted_perimeter_m


def hydraulic_depth(area_m2: float, top_width_m: float) -> float:
    """Hydraulic (mean) depth of a channel cross-section.

    Formula: D = A / T

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 2 (used as the depth term in the Froude number).

    Args:
        area_m2: Cross-sectional flow area, in m^2.
        top_width_m: Water-surface (top) width, in meters.

    Returns:
        Hydraulic depth, in meters.

    Raises:
        ZeroDivisionError: If ``top_width_m`` is zero.
    """
    return area_m2 / top_width_m


# =============================================================================
# Open-channel hydraulics: velocity and discharge
# =============================================================================


def manning_velocity(hydraulic_radius_m: float, slope_m_per_m: float, roughness_n: float) -> float:
    """Mean flow velocity via Manning's equation (SI units).

    Formula: V = (1/n) * R^(2/3) * S^(1/2)

    Reference:
        Manning, R. (1891), "On the flow of water in open channels
        and pipes", Transactions of the Institution of Civil
        Engineers of Ireland, 20, 161-207 (SI form as presented in
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 7).

    Args:
        hydraulic_radius_m: Hydraulic radius, in meters.
        slope_m_per_m: Channel bed (energy) slope, dimensionless
            (m/m). Must be non-negative.
        roughness_n: Manning's roughness coefficient, dimensionless.

    Returns:
        Mean cross-sectional flow velocity, in m/s.

    Raises:
        ValueError: If ``slope_m_per_m`` is negative or
            ``hydraulic_radius_m`` is negative.
    """
    if slope_m_per_m < 0 or hydraulic_radius_m < 0:
        raise ValueError("slope_m_per_m and hydraulic_radius_m must be non-negative.")
    return (1.0 / roughness_n) * (hydraulic_radius_m ** (2.0 / 3.0)) * math.sqrt(slope_m_per_m)


def chezy_velocity(hydraulic_radius_m: float, slope_m_per_m: float, chezy_c: float) -> float:
    """Mean flow velocity via the Chezy equation.

    Formula: V = C * sqrt(R * S)

    Reference:
        Chezy, A. (1775), as presented in Chow, V.T. (1959),
        "Open-Channel Hydraulics", McGraw-Hill, Chapter 8.

    Args:
        hydraulic_radius_m: Hydraulic radius, in meters.
        slope_m_per_m: Channel bed (energy) slope, dimensionless
            (m/m). Must be non-negative.
        chezy_c: Chezy resistance coefficient, in m^(1/2)/s.

    Returns:
        Mean cross-sectional flow velocity, in m/s.

    Raises:
        ValueError: If ``slope_m_per_m`` is negative or
            ``hydraulic_radius_m`` is negative.
    """
    if slope_m_per_m < 0 or hydraulic_radius_m < 0:
        raise ValueError("slope_m_per_m and hydraulic_radius_m must be non-negative.")
    return chezy_c * math.sqrt(hydraulic_radius_m * slope_m_per_m)


def discharge(velocity_m_s: float, area_m2: float) -> float:
    """River discharge via the continuity equation.

    Formula: Q = V * A

    Reference:
        Chow, V.T. (1959), "Open-Channel Hydraulics", McGraw-Hill,
        Chapter 1 (continuity of flow).

    Args:
        velocity_m_s: Mean cross-sectional flow velocity, in m/s.
        area_m2: Cross-sectional flow area, in m^2.

    Returns:
        Volumetric discharge, in m^3/s.
    """
    return velocity_m_s * area_m2


# =============================================================================
# Sediment transport
# =============================================================================


def suspended_sediment_concentration_from_turbidity(
    turbidity_ntu: float, coefficient_a: float, exponent_b: float
) -> float:
    """Estimate suspended-sediment concentration from turbidity.

    Formula: SSC = a * turbidity^b

    Reference:
        Rasmussen, P.P., Gray, J.R., Glysson, G.D., and Ziegler, A.C.
        (2009), "Guidelines and Procedures for Computing Time-Series
        Suspended-Sediment Concentrations and Loads from In-Stream
        Turbidity-Sensor and Streamflow Data", USGS Techniques and
        Methods, book 3, chap. C4.

    Args:
        turbidity_ntu: Turbidity, in NTU. Must be non-negative.
        coefficient_a: Site-calibrated power-law coefficient.
        exponent_b: Site-calibrated power-law exponent.

    Returns:
        Estimated suspended-sediment concentration, in mg/L.

    Raises:
        ValueError: If ``turbidity_ntu`` is negative.
    """
    if turbidity_ntu < 0:
        raise ValueError("turbidity_ntu must be non-negative.")
    return coefficient_a * (turbidity_ntu**exponent_b)


def sediment_load_from_concentration(
    ssc_mg_l: float, discharge_m3_s: float, conversion_constant: float
) -> float:
    """Suspended-sediment load from concentration and discharge.

    Formula: Qs (tons/day) = conversion_constant * SSC(mg/L) * Q(m^3/s)

    Reference:
        Porterfield, G. (1972), "Computation of Fluvial-Sediment
        Discharge", USGS Techniques of Water-Resources
        Investigations, Book 3, Chapter C3, p. 12 (the standard
        SSC-discharge load equation, conversion_constant = 0.0864 for
        metric tons/day with SSC in mg/L and Q in m^3/s).

    Args:
        ssc_mg_l: Suspended-sediment concentration, in mg/L.
        discharge_m3_s: Volumetric discharge, in m^3/s.
        conversion_constant: Unit-conversion constant (0.0864 for
            metric tons/day).

    Returns:
        Estimated suspended-sediment load, in metric tons/day.
    """
    return conversion_constant * ssc_mg_l * discharge_m3_s


def sediment_rating_curve_load(discharge_m3_s: float, coefficient_a: float, exponent_b: float) -> float:
    """Suspended-sediment discharge via a power-law rating curve.

    Formula: Qs (tons/day) = a * Q(m^3/s)^b

    Reference:
        Asselman, N.E.M. (2000), "Fitting and interpretation of
        sediment rating curves", Journal of Hydrology, 234(3-4),
        228-248.

    Args:
        discharge_m3_s: Volumetric discharge, in m^3/s. Must be
            non-negative.
        coefficient_a: Site-calibrated power-law coefficient.
        exponent_b: Site-calibrated power-law exponent.

    Returns:
        Estimated suspended-sediment discharge, in metric tons/day.

    Raises:
        ValueError: If ``discharge_m3_s`` is negative.
    """
    if discharge_m3_s < 0:
        raise ValueError("discharge_m3_s must be non-negative.")
    return coefficient_a * (discharge_m3_s**exponent_b)


__all__ = [
    "conductivity_to_tds",
    "practical_salinity_pss78",
    "oxygen_saturation_concentration_mg_l",
    "oxygen_salinity_correction_factor",
    "oxygen_pressure_correction_factor",
    "pure_water_density_kell_kg_m3",
    "salinity_density_correction_kg_m3",
    "trapezoidal_top_width",
    "trapezoidal_cross_sectional_area",
    "trapezoidal_wetted_perimeter",
    "hydraulic_radius",
    "hydraulic_depth",
    "manning_velocity",
    "chezy_velocity",
    "discharge",
    "suspended_sediment_concentration_from_turbidity",
    "sediment_load_from_concentration",
    "sediment_rating_curve_load",
]
