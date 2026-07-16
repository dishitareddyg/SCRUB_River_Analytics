"""Tests for :mod:`app.analytics.equations`.

Verifies each formula against known reference values (e.g. PSS-78 at
standard seawater conditions should recover 35 PSU; Kell's equation
should recover water's known maximum-density point) as well as
boundary and error conditions.
"""

from __future__ import annotations

import math

import pytest

from app.analytics import equations


# --- TDS -----------------------------------------------------------------


def test_conductivity_to_tds_basic() -> None:
    assert equations.conductivity_to_tds(1000.0, 0.65) == pytest.approx(650.0)


def test_conductivity_to_tds_zero_conductivity() -> None:
    assert equations.conductivity_to_tds(0.0, 0.65) == 0.0


# --- Salinity (PSS-78) -----------------------------------------------------


def test_pss78_recovers_35_psu_at_standard_seawater_conditions() -> None:
    """C(35,15,0) at T=15C should recover exactly 35 PSU by definition."""
    salinity = equations.practical_salinity_pss78(
        conductivity_us_cm=42914.0, temperature_c=15.0, reference_conductivity_us_cm=42914.0
    )
    assert salinity == pytest.approx(35.0, abs=1e-3)


def test_pss78_zero_conductivity_gives_near_zero_salinity() -> None:
    salinity = equations.practical_salinity_pss78(
        conductivity_us_cm=0.0, temperature_c=20.0, reference_conductivity_us_cm=42914.0
    )
    assert salinity == pytest.approx(0.0, abs=0.5)


def test_pss78_increases_with_conductivity() -> None:
    low = equations.practical_salinity_pss78(500.0, 20.0, 42914.0)
    high = equations.practical_salinity_pss78(5000.0, 20.0, 42914.0)
    assert high > low


# --- Dissolved oxygen ------------------------------------------------------


def test_oxygen_saturation_concentration_at_20c_matches_published_table() -> None:
    """USGS/Benson-Krause table value at 20C, freshwater, 760 mmHg is ~9.09 mg/L."""
    value = equations.oxygen_saturation_concentration_mg_l(20.0)
    assert value == pytest.approx(9.09, abs=0.05)


def test_oxygen_saturation_concentration_decreases_with_temperature() -> None:
    cold = equations.oxygen_saturation_concentration_mg_l(5.0)
    warm = equations.oxygen_saturation_concentration_mg_l(30.0)
    assert cold > warm


def test_oxygen_salinity_correction_factor_is_below_one_for_positive_salinity() -> None:
    factor = equations.oxygen_salinity_correction_factor(salinity_psu=35.0, temperature_c=20.0)
    assert 0.0 < factor < 1.0


def test_oxygen_salinity_correction_factor_is_one_at_zero_salinity() -> None:
    factor = equations.oxygen_salinity_correction_factor(salinity_psu=0.0, temperature_c=20.0)
    assert factor == pytest.approx(1.0)


def test_oxygen_pressure_correction_factor_below_one_at_altitude() -> None:
    """Barometric pressure below standard sea-level pressure should reduce saturation."""
    factor = equations.oxygen_pressure_correction_factor(
        barometric_pressure_hpa=850.0, standard_pressure_mmhg=760.0
    )
    assert factor < 1.0


def test_oxygen_pressure_correction_factor_is_one_at_standard_pressure() -> None:
    # 760 mmHg == 1013.25 hPa (standard atmosphere)
    factor = equations.oxygen_pressure_correction_factor(
        barometric_pressure_hpa=1013.25, standard_pressure_mmhg=760.0
    )
    assert factor == pytest.approx(1.0, abs=0.01)


# --- Density -----------------------------------------------------------


def test_kell_density_peaks_near_4c() -> None:
    """Pure water's known maximum density (~999.97 kg/m^3) occurs near 4C."""
    density_4c = equations.pure_water_density_kell_kg_m3(4.0)
    density_0c = equations.pure_water_density_kell_kg_m3(0.0)
    density_20c = equations.pure_water_density_kell_kg_m3(20.0)
    assert density_4c == pytest.approx(999.97, abs=0.01)
    assert density_4c > density_0c
    assert density_4c > density_20c


def test_salinity_density_correction_scales_linearly() -> None:
    correction = equations.salinity_density_correction_kg_m3(salinity_psu=10.0, coefficient_kg_m3_per_psu=0.75)
    assert correction == pytest.approx(7.5)


# --- Geometry ------------------------------------------------------------


def test_trapezoidal_rectangular_channel_area_matches_simple_case() -> None:
    """A zero side-slope trapezoid is a rectangle: A = b * h."""
    area = equations.trapezoidal_cross_sectional_area(depth_m=2.0, bed_width_m=4.0, side_slope_h_per_v=0.0)
    assert area == pytest.approx(8.0)


def test_trapezoidal_top_width() -> None:
    width = equations.trapezoidal_top_width(depth_m=1.5, bed_width_m=5.0, side_slope_h_per_v=2.0)
    assert width == pytest.approx(5.0 + 2 * 2.0 * 1.5)


def test_trapezoidal_wetted_perimeter_rectangular_case() -> None:
    """Zero side-slope: P = b + 2h (vertical banks)."""
    perimeter = equations.trapezoidal_wetted_perimeter(depth_m=2.0, bed_width_m=4.0, side_slope_h_per_v=0.0)
    assert perimeter == pytest.approx(4.0 + 2 * 2.0)


def test_hydraulic_radius_of_wide_shallow_channel_approaches_depth() -> None:
    """For a very wide rectangular channel, R approaches depth."""
    area = equations.trapezoidal_cross_sectional_area(0.5, 10000.0, 0.0)
    perimeter = equations.trapezoidal_wetted_perimeter(0.5, 10000.0, 0.0)
    radius = equations.hydraulic_radius(area, perimeter)
    assert radius == pytest.approx(0.5, rel=1e-3)


def test_hydraulic_radius_zero_perimeter_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        equations.hydraulic_radius(area_m2=1.0, wetted_perimeter_m=0.0)


def test_hydraulic_depth_rectangular_equals_actual_depth() -> None:
    """For a rectangular channel, hydraulic depth equals actual depth."""
    area = equations.trapezoidal_cross_sectional_area(1.5, 4.0, 0.0)
    top_width = equations.trapezoidal_top_width(1.5, 4.0, 0.0)
    depth = equations.hydraulic_depth(area, top_width)
    assert depth == pytest.approx(1.5)


# --- Hydraulics: velocity and discharge -------------------------------


def test_manning_velocity_basic() -> None:
    velocity = equations.manning_velocity(hydraulic_radius_m=1.0, slope_m_per_m=0.0001, roughness_n=0.035)
    expected = (1.0 / 0.035) * (1.0 ** (2 / 3)) * math.sqrt(0.0001)
    assert velocity == pytest.approx(expected)


def test_manning_velocity_negative_slope_raises() -> None:
    with pytest.raises(ValueError):
        equations.manning_velocity(hydraulic_radius_m=1.0, slope_m_per_m=-0.001, roughness_n=0.035)


def test_chezy_velocity_basic() -> None:
    velocity = equations.chezy_velocity(hydraulic_radius_m=1.0, slope_m_per_m=0.0001, chezy_c=50.0)
    assert velocity == pytest.approx(50.0 * math.sqrt(1.0 * 0.0001))


def test_manning_velocity_zero_slope_is_zero() -> None:
    assert equations.manning_velocity(1.0, 0.0, 0.035) == 0.0


def test_discharge_is_velocity_times_area() -> None:
    assert equations.discharge(velocity_m_s=2.0, area_m2=10.0) == pytest.approx(20.0)


# --- Sediment --------------------------------------------------------------


def test_ssc_from_turbidity_power_law() -> None:
    ssc = equations.suspended_sediment_concentration_from_turbidity(
        turbidity_ntu=100.0, coefficient_a=1.0, exponent_b=1.0
    )
    assert ssc == pytest.approx(100.0)


def test_ssc_from_turbidity_negative_turbidity_raises() -> None:
    with pytest.raises(ValueError):
        equations.suspended_sediment_concentration_from_turbidity(-1.0, 1.0, 1.0)


def test_sediment_load_from_concentration() -> None:
    load = equations.sediment_load_from_concentration(
        ssc_mg_l=50.0, discharge_m3_s=10.0, conversion_constant=0.0864
    )
    assert load == pytest.approx(0.0864 * 50.0 * 10.0)


def test_sediment_rating_curve_load_negative_discharge_raises() -> None:
    with pytest.raises(ValueError):
        equations.sediment_rating_curve_load(discharge_m3_s=-1.0, coefficient_a=0.01, exponent_b=1.5)


def test_sediment_rating_curve_load_zero_discharge_is_zero() -> None:
    assert equations.sediment_rating_curve_load(0.0, 0.01, 1.5) == 0.0
