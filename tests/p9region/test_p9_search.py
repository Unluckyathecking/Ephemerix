"""Offline checks of the Planet Nine region pilot's pure functions (tools/p9_search)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from p9_search import limits as L
from p9_search import population as P
from p9_search.report import recovered_above, survivors, vetted_threshold
from p9_search.tiles import dense_mask, pick_separated, select, tile_area_deg2
from p9_search.unit import choose_pass, nearest_px
from p9_search.vet import DATALAB, IRSA, cone_query, nearest_sources, sep_arcsec

from pxs.movers.limits import vmag_from_1um

CSV_TEXT = """# Planet Nine reference population; epoch of JD=2458270.0 (1 June 2018)
# Orbital elements refer to J2000 heliocentric osculating elements
#Parameters are:
# index, mass, a, e, inc, varpi, Omega, M, ra, dec, R, rad, albedo, V, ZTF, DES, PS1
index, mass, a, e, inc, varpi, Omega, M, ra, dec, R, rad, albedo, V, ZTF, DES, PS1
0, 6.2, 380, 0.2, 16, 246, 96, 170, 45.0, 10.0, 500.0, 2.9, 0.5, 21.3, 0, 0, 0
1, 6.2, 380, 0.2, 16, 246, 96, 170, 60.0, 15.0, 400.0, 2.9, 0.5, 20.1, 1, 0, 0
"""


def test_parse_reference_population_and_survivor_flags() -> None:
    pop = P.parse(CSV_TEXT)
    assert len(pop) == 2
    assert pop.ra.tolist() == [45.0, 60.0] and pop.r_au.tolist() == [500.0, 400.0]
    assert pop.vmag.tolist() == [21.3, 20.1]
    assert pop.survives.tolist() == [True, False]


def test_local_density_is_fraction_per_square_degree() -> None:
    rng = np.random.default_rng(0)
    # 1000 points uniform in a 1-deg cap around (0, 0) plus 1000 far away.
    r = np.sqrt(rng.uniform(0, 1, 1000))
    th = rng.uniform(0, 2 * np.pi, 1000)
    ra = np.concatenate([r * np.cos(th), 180 + rng.uniform(-5, 5, 1000)]) % 360
    dec = np.concatenate([r * np.sin(th), rng.uniform(-5, 5, 1000)])
    xyz = P.unit_vectors(ra, dec)
    d = P.local_density(xyz, P.unit_vectors(np.array([0.0]), np.array([0.0])), 1.0)
    # half the population inside a cap of area ~pi deg^2
    assert d[0] == pytest.approx(0.5 / P.cap_area_deg2(1.0), rel=1e-6)
    assert P.cap_area_deg2(1.0) == pytest.approx(math.pi, rel=1e-3)


def test_dense_mask_keeps_top_fraction_of_eligible_only() -> None:
    density = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    eligible = np.array([True, True, True, True, False])
    m = dense_mask(density, eligible, 0.5)
    assert m.tolist() == [False, False, True, True, False]


def test_pick_separated_enforces_minimum_separation() -> None:
    ra = np.array([0.0, 0.5, 2.0, 2.2, 5.0])
    xyz = P.unit_vectors(ra, np.zeros(5))
    got = pick_separated(xyz, np.arange(5), 10, 1.0)
    assert got == [0, 2, 4]


def test_select_is_seeded_and_lands_in_the_dense_cluster_off_the_plane() -> None:
    rng = np.random.default_rng(1)
    # Dense cluster at (40, 0); sparse background everywhere else.
    ra = np.concatenate([40 + rng.normal(0, 1.5, 4000), rng.uniform(0, 360, 2000)]) % 360
    dec = np.concatenate([rng.normal(0, 1.5, 4000), rng.uniform(-60, 60, 2000)])
    b = np.full(len(ra), 50.0)
    b[ra > 41] = 5.0  # pretend the east half of the cluster is in the plane
    t1 = select(ra, dec, b, seed=7, n=6, kernel_deg=1.0, min_sep_deg=0.5)
    t2 = select(ra, dec, b, seed=7, n=6, kernel_deg=1.0, min_sep_deg=0.5)
    assert [(t.ra, t.dec) for t in t1] == [(t.ra, t.dec) for t in t2]
    assert len(t1) == 6 and [t.rank for t in t1] == list(range(1, 7))
    assert all(abs(t.b_deg) >= 15 for t in t1)
    assert all(abs(t.ra - 40) < 5 and abs(t.dec) < 5 for t in t1)
    assert tile_area_deg2(20.0) == pytest.approx(1 / 9)


def test_wilson_interval_known_values() -> None:
    lo, hi = L.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert L.wilson(0, 10)[0] == 0.0 and L.wilson(10, 10)[1] == pytest.approx(1.0)
    assert all(math.isnan(v) for v in L.wilson(0, 0))


def test_binned_completeness_and_flux_at() -> None:
    edges = np.array([10.0, 20.0, 40.0, 80.0, 160.0])
    flux = np.array([15, 15, 30, 30, 60, 60, 100, 100.0])
    rec = np.array([0, 0, 0, 1, 1, 1, 1, 1])
    b = L.binned(flux, rec, edges)
    assert b["n"] == [2, 2, 2, 2] and b["k"] == [0, 1, 2, 2]
    assert b["completeness"] == [0.0, 0.5, 1.0, 1.0]
    f50 = L.flux_at(b, 0.5)
    assert f50 == pytest.approx(math.sqrt(20 * 40), rel=1e-6)  # the 0.5 bin centre
    assert 40 < L.flux_at(b, 0.9) < 80


def test_completeness_at_interpolates_in_log_flux_and_clamps() -> None:
    b = {"flux_ujy": [10.0, 100.0], "completeness": [0.0, 1.0]}
    got = L.completeness_at(b, np.array([1.0, 10.0, math.sqrt(1000.0), 100.0, 1e4]))
    assert got.tolist() == pytest.approx([0.0, 0.0, 0.5, 1.0, 1.0])


def test_flux_from_vmag_inverts_vmag_from_1um() -> None:
    for f in (20.0, 68.0, 400.0):
        assert L.flux_1um_from_vmag(vmag_from_1um(f)) == pytest.approx(f, rel=1e-9)
    assert L.ab_from_ujy(3631e6) == pytest.approx(0.0)


def test_reach_au_takes_farthest_bright_enough_distance() -> None:
    assert L.reach_au([200, 300, 400], [18.0, 19.0, 20.0], 19.5) == 300.0
    assert L.reach_au([200, 300], [20.0, 21.0], 19.0) is None


def test_excluded_fraction_counts_only_members_inside_motion_distance() -> None:
    comp = np.array([1.0, 1.0, 0.5, 0.0])
    r = np.array([300.0, 600.0, 300.0, 300.0])
    got = L.excluded_fraction(1e-4, 0.1, comp, r, d_motion_au=500.0)
    assert got == pytest.approx(1e-4 * 0.1 * (1.0 + 0.5) / 4)
    assert L.excluded_fraction(1e-4, 0.1, np.zeros(0), np.zeros(0), 500.0) == 0.0


def test_choose_pass_prefers_most_window_frames_with_reference_then_earliest() -> None:
    s = [{"index": 0, "n_window": 50, "has_reference": True},
         {"index": 1, "n_window": 60, "has_reference": False},
         {"index": 2, "n_window": 55, "has_reference": True},
         {"index": 3, "n_window": 55, "has_reference": True}]
    assert choose_pass(s) == 2
    assert choose_pass([{"index": 0, "n_window": 9, "has_reference": False}]) is None


def test_limit_counts_only_injections_above_the_vetted_threshold() -> None:
    assert vetted_threshold({"null_max": 12.5}) == 12.5
    assert vetted_threshold({"null_max": 4.0}) == 7.0
    assert vetted_threshold({"null_max": None}) == 7.0
    rec = np.array([1, 1, 1, 0])
    snr = np.array([13.0, 12.5, math.nan, 20.0])
    assert recovered_above(rec, snr, 12.5).tolist() == [True, False, False, False]


def test_survivors_are_peaks_above_null_max() -> None:
    base = {"null_max": 9.0, "peaks_ge7": [{"snr": 8.0}, {"snr": 9.5}, {"snr": 12.0}]}
    assert [p["snr"] for p in survivors(base)] == [9.5, 12.0]
    assert len(survivors({"null_max": None, "peaks_ge7": [{"snr": 7.1}]})) == 1


def test_nearest_px_and_separations() -> None:
    assert nearest_px(np.array([0.0, 3.0]), np.array([0.0, 4.0]), 3.0, 0.0) == 3.0
    assert nearest_px(np.array([]), np.array([]), 1.0, 1.0) is None
    assert sep_arcsec(10.0, 0.0, 10.0, 1 / 3600) == pytest.approx(1.0)
    assert sep_arcsec(359.9999, 0.0, 0.0001, 0.0) == pytest.approx(0.72, abs=1e-3)
    rows = [{"ra": "10.0", "dec": "0.01", "w1mpro": "15.0"},
            {"ra": "10.0", "dec": "0.0", "w1mpro": ""}]
    near = nearest_sources(rows, 10.0, 0.0, ("w1mpro",))
    assert near[0]["sep_arcsec"] == 0.0 and near[0]["w1mpro"] is None
    assert near[1]["sep_arcsec"] == pytest.approx(36.0) and near[1]["w1mpro"] == 15.0
    q = cone_query(DATALAB, "catwise2020.main", "ra", "dec", ("w1mpro",), 10.0, 0.0)
    assert "q3c_radial_query(ra, dec, 10.000000, 0.000000, 0.016667)" in q
    q = cone_query(IRSA, "catwise_2020", "ra_pm", "dec_pm", ("w1mpro",), 10.0, 0.0)
    assert "ra_pm AS ra" in q and "CIRCLE('ICRS', 10.000000, 0.000000, 0.016667)" in q
