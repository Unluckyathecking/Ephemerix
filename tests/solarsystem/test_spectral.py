"""Band fluxes, controls subtraction, solar reference, reflectance and band depths."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pxs.solarsystem.bands import band_depths, reading
from pxs.solarsystem.phot import BANDS, BandFlux, band_flux, subtract
from pxs.solarsystem.solar import (
    RPoint,
    reflectance,
    solar_fnu,
    thermal_fraction,
)
from pxs.sources import SPHEREX_WINDOWS

from .conftest import spec_point


def test_bands_match_detector_windows():
    assert BANDS == SPHEREX_WINDOWS


def test_band_flux_is_inverse_variance_mean_of_usable_points():
    pts = [spec_point(0.8, 0.5, 0.1), spec_point(0.9, 0.7, 0.1), spec_point(1.0, 9.9, 0.1,
                                                                            flagged=True),
           spec_point(1.2, 5.0, 0.1)]
    b = band_flux(pts, "spx-b1")
    assert b.n == 2 and b.flux_mjy == pytest.approx(0.6)
    assert b.err_mjy == pytest.approx(0.1 / math.sqrt(2))
    assert band_flux([], "spx-b2").n == 0


def test_subtract_control():
    d = subtract(BandFlux("spx-b1", 5, 0.186, 0.013), BandFlux("spx-b1", 105, 0.032, 0.004))
    assert d.flux_mjy == pytest.approx(0.154) and d.err_mjy == pytest.approx(math.hypot(.013, .004))
    assert math.isnan(subtract(d, BandFlux("spx-b1", 0, math.nan, math.nan)).flux_mjy)


def test_solar_reference_shape():
    assert solar_fnu(1.25) == pytest.approx(1.0, rel=0.01)
    # F_nu of the Sun falls roughly as lambda^-1.5..-2 in the near-infrared
    assert 2.0 < solar_fnu(1.25) / solar_fnu(3.0) < 4.5
    narrow, wide = solar_fnu(2.0, 0.0), solar_fnu(2.0, 0.05)
    assert wide == pytest.approx(narrow, rel=0.03)
    with pytest.raises(ValueError):
        solar_fnu(6.0)


def test_solar_coloured_body_has_flat_reflectance():
    pts = [{"wl_um": w, "bw_um": 0.02, "flux": 0.3 * solar_fnu(w, 0.02), "err": 0.003,
            "flagged": False} for w in np.linspace(0.8, 4.8, 60)]
    refl, norm = reflectance(pts)
    assert norm == pytest.approx(0.3, rel=1e-3)
    assert all(r.refl == pytest.approx(1.0, rel=1e-3) for r in refl)
    assert all(not d.detected for d in band_depths(refl))


def test_injected_water_band_is_measured():
    pts = []
    for w in np.linspace(0.8, 2.4, 80):
        r = 0.4 if 1.48 <= w < 1.60 else 1.0
        pts.append({"wl_um": w, "bw_um": 0.02, "flux": r * solar_fnu(w, 0.02), "err": 0.01,
                    "flagged": False})
    refl, _ = reflectance(pts)
    d = {x.label: x for x in band_depths(refl)}
    assert d["1.5 um (H2O)"].depth == pytest.approx(0.6, abs=0.01)
    assert d["1.5 um (H2O)"].detected and not d["2.0 um (H2O)"].detected
    assert math.isnan(d["3.3 um (CH4; H2O wing)"].ratio)  # no data there
    s = reading(list(d.values()), "water ice")
    assert "1.5 um (H2O)" in s and "Published: water ice." in s


def test_reading_without_detection():
    pts = [RPoint(1.1, 0.02, 1.0, 0.5), RPoint(1.5, 0.02, 0.9, 0.5)]
    assert reading(band_depths(pts), "").startswith("No absorption band is detected")


def test_thermal_is_negligible_for_tnos_but_not_main_belt():
    assert thermal_fraction(5.0, 50.0, 0.7, bond_albedo=0.4) < 1e-10
    assert thermal_fraction(4.5, 2.5, 0.1, bond_albedo=0.05) > 1.0
    assert thermal_fraction(2.5, 2.5, 0.1, bond_albedo=0.05) < 0.05


def test_clip_drops_a_star_hit_but_keeps_colour():
    from pxs.solarsystem.phot import clip
    pts = [spec_point(0.8 + 0.02 * i, 0.5 + 0.01 * i, 0.02) for i in range(8)]
    hit = spec_point(0.95, 5.0, 0.02)
    assert len(clip([*pts, hit])) == 8 and hit not in clip([*pts, hit])


def test_ice_pattern_from_2_0_and_2_3_depths():
    from pxs.solarsystem.bands import Depth, ice_pattern
    def d(label, depth):
        return Depth(label, (0, 1), 3, 3, 1 - depth, 0.05)
    assert ice_pattern([d("2.0 um (H2O)", 0.6), d("2.3 um (CH4)", 0.2)]) == "water ice"
    assert ice_pattern([d("2.0 um (H2O)", 0.2), d("2.3 um (CH4)", 0.7)]) == "methane ice"
    assert ice_pattern([d("2.0 um (H2O)", 0.5), d("2.3 um (CH4)", 0.45)]) == ""


def test_thermal_cutoff():
    from pxs.solarsystem.solar import thermal_cutoff_um
    assert thermal_cutoff_um(50.0) is None and thermal_cutoff_um(18.0) is None
    assert 3.7 < thermal_cutoff_um(4.1) < 4.1
    assert thermal_cutoff_um(2.5) < thermal_cutoff_um(4.1)


def test_saturated_band_is_a_lower_limit_not_an_impossible_depth():
    # Haumea 2026a at 3.0 um: in-band reflectance below zero by noise, -0.159 +- 0.106.
    from pxs.solarsystem.bands import Depth
    d = Depth("3.0 um (H2O)", (2.90, 3.15), 3, 26, -0.159, 0.106)
    assert d.saturated
    assert d.depth_min == pytest.approx(1 - 1.645 * 0.106)  # the clamp: no credit for ratio < 0
    out = d.to_dict()
    assert out["depth"] is None and out["saturated"] is True
    assert out["depth_min"] == pytest.approx(0.826, abs=1e-3)
    assert out["ratio"] == -0.159 and out["err"] == 0.106  # the measurement stays checkable
    s = reading([d], "")
    assert "saturated" in s and "deeper than 83% (95% confidence)" in s
    assert "116%" not in s and "100%" not in s


def test_measured_band_keeps_its_depth():
    from pxs.solarsystem.bands import Depth
    d = Depth("2.0 um (H2O)", (1.95, 2.10), 4, 26, 0.261, 0.051)
    assert not d.saturated and d.depth_min is None
    assert d.to_dict()["depth"] == pytest.approx(0.739) and d.to_dict()["saturated"] is False
    assert "2.0 um (H2O) 74% +- 5%" in reading([d], "")


def test_band_depths_from_points_below_zero_never_exceed_100_percent():
    pts = [RPoint(w, 0.02, 1.0, 0.05) for w in np.linspace(0.76, 1.29, 20)]
    pts += [RPoint(w, 0.02, -0.15, 0.2) for w in (2.92, 3.0, 3.1)]
    (d,) = [x for x in band_depths(pts) if x.label.startswith("3.0")]
    assert d.saturated and d.to_dict()["depth"] is None and 0 < d.depth_min < 1
