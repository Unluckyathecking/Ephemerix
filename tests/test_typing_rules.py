"""Rules of the classifier: comparison families, parameter penalty, gate, band test, edges
and type range. Synthetic spectra use SPHEREx-like sampling (about 100 points, 0.75-5 um),
fixed seeds, and noise sigma = (0.5 f + 0.5 median f) / (S/N)."""

import numpy as np
import pytest

from pxs.spectra import bin_edges
from pxs.typing import load_templates, match_spectrum
from pxs.typing.core import Analysis, Candidate
from pxs.typing.decide import _class, type_range
from pxs.typing.features import Band, band_depth
from pxs.typing.fit import fit_two, noise_scale
from pxs.typing.models import N_PARAMS, bb_fnu, extinction_mag, power_law_fnu

_E = bin_edges(0.75, 5.0)
WL = 0.5 * (_E[:-1] + _E[1:])
WL = WL[WL <= 5.0]


def tpl(label):
    m = load_templates()[label]
    return lambda wl: np.interp(wl, m.wl_um, m.flam) * wl**2


def observe(fn, snr, seed, wl=WL, err_factor=1.0):
    f = fn(wl)
    f = 2.0 * f / f.mean()
    sig = (0.5 * np.abs(f) + 0.5 * np.median(np.abs(f))) / snr
    rng = np.random.default_rng(seed)
    return wl, f + rng.normal(0, 1, f.size) * sig, sig * err_factor


def mix(f1, f2, frac2, at=2.2):
    def f(wl):
        r1, r2 = f1(np.array([at]))[0], f2(np.array([at]))[0]
        return (1 - frac2) * f1(wl) / r1 + frac2 * f2(wl) / r2
    return f


ADVERSARIES = {
    "4500 K, A_V 5": lambda wl: bb_fnu(wl, 4500, 5),
    "3000 K, A_V 2": lambda wl: bb_fnu(wl, 3000, 2),
    "6000 K, A_V 20": lambda wl: bb_fnu(wl, 6000, 20),
    "flat F_nu": lambda wl: power_law_fnu(wl, 0.0),
    "F_nu ~ lambda": lambda wl: power_law_fnu(wl, 1.0),
    "F_nu ~ lambda^2": lambda wl: power_law_fnu(wl, 2.0),
    "dust 700 K": lambda wl: bb_fnu(wl, 700, 0),
    "dust 1500 K": lambda wl: bb_fnu(wl, 1500, 0),
    "galaxy 3800 K at z 0.6": lambda wl: bb_fnu(wl / 1.6, 3800, 0),
    "T Tauri 4000 K + 800 K": mix(lambda wl: bb_fnu(wl, 4000, 1), lambda wl: bb_fnu(wl, 800, 0),
                                  0.5),
}


@pytest.mark.parametrize("name", list(ADVERSARIES))
@pytest.mark.parametrize("snr", [10, 30, 100])
def test_adversaries_never_called_brown_dwarf(name, snr):
    for seed in range(3):
        r = match_spectrum(*observe(ADVERSARIES[name], snr, seed))
        assert r["class"] != "brown dwarf", (name, snr, seed, r["verdict"])


@pytest.mark.parametrize("name", list(ADVERSARIES))
def test_adversaries_with_errors_three_times_too_small(name):
    r = match_spectrum(*observe(ADVERSARIES[name], 10, 1, err_factor=1 / 3))
    assert r["class"] != "brown dwarf"


@pytest.mark.parametrize("name", list(ADVERSARIES))
def test_adversaries_sparse_sampling(name):
    r = match_spectrum(*observe(ADVERSARIES[name], 30, 2, wl=WL[::4]))
    assert r["class"] != "brown dwarf"


def test_reddened_star_named_as_such():
    r = match_spectrum(*observe(ADVERSARIES["4500 K, A_V 5"], 30, 0))
    assert r["class"] == "star" and r["confidence"] == "high"
    assert r["verdict"] == "Looks like a star dimmed and reddened by dust, not a brown dwarf."
    assert r["type_range"] is None and not r["range_open_warm"] and not r["range_open_cold"]


@pytest.mark.parametrize("name", ["flat F_nu", "F_nu ~ lambda^2", "T Tauri 4000 K + 800 K",
                                  "dust 1500 K"])
def test_red_featureless_sources_are_not_brown_dwarfs(name):
    r = match_spectrum(*observe(ADVERSARIES[name], 30, 0))
    assert r["class"] == "not a brown dwarf"
    assert r["verdict"] == "Looks like a dusty or young red source, not a brown dwarf."


def test_cold_dust_may_be_colder_than_the_grid():
    r = match_spectrum(*observe(lambda wl: bb_fnu(wl, 400, 0), 30, 0))
    assert r["class"] == "uncertain" and r["confidence"] == "low"
    assert "colder than the coldest template (Y1)" in r["verdict"]


@pytest.mark.parametrize("label", [k for k in load_templates() if k not in ("M8", "M9")])
@pytest.mark.parametrize("snr", [10, 30])
def test_true_brown_dwarfs_still_called_brown_dwarfs(label, snr):
    for seed in range(2):
        r = match_spectrum(*observe(tpl(label), snr, seed))
        assert r["class"] == "brown dwarf", (label, snr, r["verdict"])
        assert r["bands_detected"]


def test_true_brown_dwarfs_with_errors_three_times_too_small():
    for label in ("L3", "T2", "T7", "Y0"):
        r = match_spectrum(*observe(tpl(label), 10, 0, err_factor=1 / 3))
        assert r["class"] == "brown dwarf"


def test_warm_edge_is_uncertain_and_open():
    for label in ("M8", "M9"):
        r = match_spectrum(*observe(tpl(label), 30, 0))
        assert r["class"] == "uncertain" and r["confidence"] == "low"
        assert r["type_range"][0] == "M8" and r["range_open_warm"]
        assert r["verdict"].endswith("the templates start at M8, so it may be an ordinary star.")
        assert " or warmer" in r["verdict"]


def test_cold_edge_y1_says_or_colder():
    r = match_spectrum(*observe(tpl("Y1"), 30, 0))
    assert r["class"] == "brown dwarf"
    assert r["type_range"] == ["Y0", "Y1"] and r["range_open_cold"] and not r["range_open_warm"]
    assert "Y1 or colder" in r["verdict"]


def test_range_touching_cold_edge_is_open():
    r = match_spectrum(*observe(tpl("Y0"), 30, 0))
    assert r["type_range"][1] == "Y1" and r["range_open_cold"]
    assert "or colder" in r["verdict"]


# --- parameter counting and scores -------------------------------------------------------

def _cand(label, chi2, k=2, family="brown dwarf"):
    return Candidate(label, family, chi2, k, lambda wl: np.ones_like(wl), (label,))


def _analysis(chi2_by_type, n=80, others=()):
    temps = tuple(_cand(t, c) for t, c in chi2_by_type.items())
    full = {lab: 1e6 for lab in load_templates()}
    full.update(chi2_by_type)
    temps = tuple(_cand(t, c) for t, c in full.items())
    wl = np.linspace(1, 5, n)
    return Analysis(wl, wl, wl, n, temps, tuple(others), 1.0, 1.0)


def test_parameter_counts():
    assert N_PARAMS == {"brown dwarf": 2, "blackbody": 3, "power law": 2, "star + dust": 5}


def test_score_penalises_extra_parameters():
    a = _analysis({"T5": 100.0})
    two, five = _cand("x", 100.0, k=2), _cand("y", 100.0, k=5)
    assert a.score(five) - a.score(two) == pytest.approx(3 * np.log(80))


def test_score_rescales_chi2():
    a = _analysis({"T5": 100.0})
    b = Analysis(a.wl, a.d, a.sigma, a.n_used, a.templates, a.others, 4.0, 1.0)
    c = _cand("x", 400.0)
    assert b.score(c) == pytest.approx(100.0 + 2 * np.log(80))


# --- type range --------------------------------------------------------------------------

def test_range_floor_is_one_subtype_either_side():
    rng, warm, cold = type_range(_analysis({"T5": 10.0}))
    assert rng == ["T4", "T6"] and not warm and not cold


def test_range_is_contiguous_and_crosses_letters():
    rng, _, _ = type_range(_analysis({"L9": 10.0, "T0": 11.0, "T1": 40.0, "T2": 12.0}))
    assert rng == ["L8", "T2"]


def test_range_widens_with_poor_fit():
    # best reduced chi2 = 780 / 78 = 10, so the cutoff is 4 x 10 = 40 above the best
    rng, _, _ = type_range(_analysis({"T5": 780.0, "T7": 815.0, "T3": 830.0}))
    assert rng == ["T4", "T7"]


def test_range_open_at_both_edges():
    assert type_range(_analysis({"M8": 1.0}))[1:] == (True, False)
    assert type_range(_analysis({"Y1": 1.0}))[1:] == (False, True)


# --- gate, band test and decision rules --------------------------------------------------

def test_noise_scale_measures_white_noise_and_ignores_smooth_misfit():
    rng = np.random.default_rng(0)
    x = np.linspace(0, 1, 4000)
    assert noise_scale(3.0 * rng.normal(size=4000)) == pytest.approx(3.0, rel=0.1)
    assert noise_scale(rng.normal(size=4000) + 20 * np.sin(3 * x)) == pytest.approx(1.0, rel=0.1)


def test_nothing_fits_is_refused():
    # a square wave: smooth in neighbouring points, so the noise scale stays near 1,
    # but no template or comparison model can follow it
    f = np.where((WL * 3).astype(int) % 2 == 0, 1.0, 3.0)
    r = match_spectrum(WL, f, 0.02 * f)
    assert r["class"] == "uncertain" and r["confidence"] == "low"
    assert r["verdict"].startswith("Does not look like any brown-dwarf template")


def test_gate_is_robust_to_errors_too_small():
    r = match_spectrum(*observe(tpl("T6"), 10, 3, err_factor=1 / 3))
    assert r["class"] == "brown dwarf"


def test_band_depth_zero_for_power_law_and_not_positive_for_blackbodies():
    wl = np.linspace(1.0, 5.0, 200)
    sig = np.full(wl.size, 1e-6)
    args = ((3.10, 3.55), (2.02, 2.40), (3.70, 4.15))
    for a in (-2.0, 0.0, 3.0):
        assert band_depth(wl, power_law_fnu(wl, a), sig, *args)[0] == pytest.approx(0, abs=1e-3)
    for t, av in ((3000, 0), (5000, 10), (800, 0), (400, 0)):
        assert band_depth(wl, bb_fnu(wl, t, av), sig * 1e-9, *args, min_snr=0)[0] <= 1e-3


def test_band_depth_large_for_t8_methane():
    wl = np.linspace(1.0, 4.9, 200)
    f = tpl("T8")(wl)
    d, _ = band_depth(wl, f, f * 1e-3, (3.10, 3.55), (2.02, 2.40), (3.70, 4.15))
    assert d > 0.5


def test_band_depth_none_when_window_empty_or_faint():
    wl = np.array([1.0, 3.3, 4.0])
    f = np.array([1.0, 0.5, 1.0])
    assert band_depth(wl, f, f * 0.01, (3.10, 3.55), (2.02, 2.40), (3.70, 4.15)) is None
    wl = np.array([2.2, 3.3, 4.0])
    assert band_depth(wl, f, f, (3.10, 3.55), (2.02, 2.40), (3.70, 4.15)) is None


def _band(detected):
    return Band("CH4 3.3 um", 0.5, 0.05, 0.8, True, detected)


def test_class_needs_a_detected_band():
    bd, other = _cand("T5", 10.0), _cand("star (3000 K)", 100.0, 3, "star")
    other = Candidate(other.label, "star", 100.0, 3, other.curve, (3000.0, 0.0, 100.0))
    assert _class(80, 1.0, 50.0, bd, other, (_band(True),)) == ("brown dwarf", "fit")
    assert _class(80, 1.0, 50.0, bd, other, (_band(False),)) == ("uncertain", "no bands")


def test_class_rules_for_margin_gate_and_points():
    bd = _cand("T5", 10.0)
    star = Candidate("star (3000 K)", "star", 100.0, 3, bd.curve, (3000.0, 0.0, 100.0))
    bands = (_band(True),)
    assert _class(10, 1.0, 50.0, bd, star, bands) == ("uncertain", "few points")
    assert _class(80, 12.0, 50.0, bd, star, bands) == ("uncertain", "no fit")
    assert _class(80, 5.0, 20.0, bd, star, bands) == ("uncertain", "no fit")  # poor fit, small margin
    assert _class(80, 5.0, 40.0, bd, star, bands) == ("brown dwarf", "fit")
    assert _class(80, 1.0, 5.0, bd, star, bands) == ("uncertain", "tie")
    assert _class(80, 1.0, -50.0, bd, star, bands) == ("star", "fit")
    assert _class(80, 1.0, 50.0, _cand("M9", 1.0), star, bands) == ("uncertain", "warm edge")


def test_class_cold_edge_rules():
    bands = (_band(False),)
    dust = Candidate("dust (400 K)", "dust", 1.0, 3, lambda w: w, (400.0, 0.0, 9.0))
    warm_dust = Candidate("dust (1200 K)", "dust", 1.0, 3, lambda w: w, (1200.0, 0.0, 9.0))
    star = Candidate("star (3000 K, A_V 20)", "star", 1.0, 3, lambda w: w, (3000.0, 20.0, 9.0))
    assert _class(80, 1.0, -50.0, _cand("T5", 9.0), dust, bands) == ("uncertain", "cold edge")
    assert _class(80, 1.0, -50.0, _cand("Y1", 9.0), warm_dust, bands) == ("uncertain",
                                                                          "cold edge")
    assert _class(80, 1.0, -50.0, _cand("T5", 9.0), warm_dust, bands) == ("not a brown dwarf",
                                                                          "fit")
    assert _class(80, 1.0, -50.0, _cand("Y1", 9.0), star, bands) == ("star", "fit")


# --- fitting -----------------------------------------------------------------------------

def test_fit_two_matches_scipy_nnls():
    from scipy.optimize import nnls

    rng = np.random.default_rng(1)
    a, b = rng.uniform(0, 1, (50, 30)), rng.uniform(0, 1, (50, 30))
    d = rng.normal(1, 0.5, 30)
    w = rng.uniform(0.5, 2, 30)
    sa, sb, chi2 = fit_two(a, b, d, w)
    for i in range(50):
        m = np.vstack([a[i], b[i]]).T * np.sqrt(w)[:, None]
        coef, res = nnls(m, d * np.sqrt(w))
        assert chi2[i] == pytest.approx(res**2, rel=1e-6, abs=1e-9)
        assert (sa[i], sb[i]) == pytest.approx(tuple(coef), abs=1e-6)


def test_only_star_family_labels_begin_with_star():
    # The page treats a best type beginning with "star" as "not a brown dwarf".
    r = match_spectrum(*observe(lambda wl: bb_fnu(wl, 400, 0), 30, 0))
    for c in r["candidates"]:
        assert c["type"].startswith("star") == (c["family"] == "star"), c


def test_extinction_law_normalisation():
    assert extinction_mag(np.array([2.2]), 1.0)[0] == pytest.approx(0.112)
    assert extinction_mag(np.array([1.25]), 1.0)[0] == pytest.approx(0.29, abs=0.01)
