"""Brightness of a distant planet: reflected light, blackbody emission, band means, magnitudes."""

from __future__ import annotations

import math

import pytest

from pxs.planetx import flux, photometry
from pxs.planetx.photometry import SPHEREX_BANDS, WISE_BANDS, Band

W1, W2 = WISE_BANDS


def test_ab_round_trip_and_zero_point():
    assert photometry.ab_mag(3631e6) == pytest.approx(0.0)
    assert photometry.ujy_from_ab(photometry.ab_mag(12.3)) == pytest.approx(12.3)
    assert photometry.ab_mag(1.0) == pytest.approx(23.9, abs=0.001)  # 1 uJy is AB 23.9


def test_wise_vega_to_ab_offsets():
    # WISE Explanatory Supplement sec. 4.4h, Table 3
    assert W1.vega_to_ab == pytest.approx(2.699)
    assert W2.vega_to_ab == pytest.approx(3.339)


def test_spherex_band_edges_follow_hui_2026():
    edges = [(b.lo_um, b.hi_um) for b in SPHEREX_BANDS]
    assert edges == [(0.75, 1.11), (1.11, 1.64), (1.64, 2.42), (2.42, 3.82), (3.82, 4.42),
                     (4.42, 5.00)]


def test_reflected_light_falls_as_distance_to_the_fourth():
    f1 = flux.reflected_ujy(1.25, r_au=300, radius_re=3.66, albedo=0.41)
    f2 = flux.reflected_ujy(1.25, r_au=600, radius_re=3.66, albedo=0.41)
    assert f1 / f2 == pytest.approx(16.0, rel=1e-9)


def test_reflected_light_scales_with_albedo_and_area():
    base = flux.reflected_ujy(2.0, r_au=500, radius_re=2.0, albedo=0.2)
    assert flux.reflected_ujy(2.0, r_au=500, radius_re=4.0, albedo=0.2) == pytest.approx(4 * base)
    assert flux.reflected_ujy(2.0, r_au=500, radius_re=2.0, albedo=0.4) == pytest.approx(2 * base)


def test_sun_w1_matches_published_solar_colour():
    # V_sun = -26.76 (Vega; Willmer 2018) and (V - W1)_sun = 1.608 (Casagrande et al. 2012)
    # give W1_sun = -28.37 Vega = -25.67 AB. The top-hat band is an approximation: 0.1 mag.
    sun_w1_ujy = photometry.band_mean(flux.sun_ujy_1au, W1)
    assert photometry.ab_mag(sun_w1_ujy) == pytest.approx(-28.368 + 2.699, abs=0.1)


def test_reproduces_linder_mordasini_2016_nominal_planet_nine():
    # 10 M_E, R = 3.66 R_E, geometric albedo 0.41, at 700 au: W1 = 20.1 (Vega), A&A 589, A134.
    w1_ujy = flux.band_flux_ujy(W1, r_au=700, radius_re=3.66, albedo=0.41, teff_k=47)
    assert photometry.ab_mag(w1_ujy) - W1.vega_to_ab == pytest.approx(20.1, abs=0.15)


def test_v_magnitude_matches_linder_mordasini_2016():
    assert flux.v_mag(700, 3.66, 0.41) == pytest.approx(21.7, abs=0.1)
    assert flux.v_mag(1120, 3.66, 0.41) == pytest.approx(23.7, abs=0.1)


def test_blackbody_band_mean_matches_analytic_integral():
    # Mean of F_nu over a top-hat in wavelength, compared with direct quadrature of Planck.
    band = Band("test", 3.0, 4.0)
    t, r_re, d_au = 300.0, 1.0, 1.0
    n = 20000
    ws = [3.0 + (i + 0.5) / n for i in range(n)]
    exact = sum(flux.thermal_ujy(w, t, r_re, d_au) for w in ws) / n
    got = photometry.band_mean(lambda w: flux.thermal_ujy(w, t, r_re, d_au), band)
    assert got == pytest.approx(exact, rel=1e-4)


def test_planck_against_hand_value():
    # B_nu(2 um, 1000 K) = 2 h nu^3 / c^2 / (exp(h nu / k T) - 1)
    h, c, k = 6.62607015e-34, 2.99792458e8, 1.380649e-23
    nu = c / 2e-6
    expected = 2 * h * nu**3 / c**2 / math.expm1(h * nu / (k * 1000.0))
    assert flux.planck_nu(2.0, 1000.0) == pytest.approx(expected, rel=1e-12)


def test_thermal_is_negligible_at_3_to_5_um_for_a_47_k_blackbody():
    refl = flux.reflected_ujy(4.6, r_au=700, radius_re=3.66, albedo=0.41)
    therm = flux.thermal_ujy(4.6, 47.0, 3.66, 700)
    assert therm < 1e-6 * refl
