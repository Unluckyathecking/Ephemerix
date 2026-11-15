"""The fit's own significance and the wider range used for faint spectra (pxs.typegate)."""

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

from pxs.typing import load_templates, match_spectrum

FIXTURES = Path(__file__).parent / "fixtures" / "spectra"


def shape(label):
    """(wavelengths um, F_nu shape) of a template on its own grid."""
    t = load_templates()[label]
    return t.wl_um, t.flam * t.wl_um**2


def fixture(slug):
    fix = json.loads((FIXTURES / f"{slug}.json").read_text())
    return (np.array(fix[k], dtype=float) for k in ("wl_um", "flux_mjy", "err_mjy"))


def test_detection_sigma_is_the_matched_filter_signal_to_noise():
    # A noiseless T8 with the same error on 20 points: the best model has chi2 = 0, so the
    # significance is sqrt(sum (flux / err)^2). Under 25 points, so none is dropped.
    wl, f = shape("T8")
    wl, f = wl[5::5][:20], f[5::5][:20]
    err = np.full(wl.size, 5.0 * f.max())  # far above the 10% error floor
    r = match_spectrum(wl, f, err)
    assert r["detection_sigma"] == pytest.approx(float(np.sqrt(np.sum((f / err) ** 2))), abs=0.05)
    assert r["detection_sigma"] < 1.0


def test_noise_alone_is_not_significant():
    wl, _ = shape("T8")
    rng = np.random.default_rng(3)
    worst = max(match_spectrum(wl, rng.normal(0.0, 1.0, wl.size), np.ones(wl.size))
                ["detection_sigma"] for _ in range(20))
    assert worst < 5.0


def test_a_spectrum_no_template_can_scale_to_gives_no_numeric_warning():
    # Mostly negative fluxes: every template's best scale is zero, and the band depths of a
    # zero template used to divide by zero.
    wl, _ = shape("T8")
    flux = np.random.default_rng(0).normal(-1.0, 0.3, wl.size)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        r = match_spectrum(wl, flux, np.full(wl.size, 0.3))
    assert r["class"] == "uncertain" and r["bands_detected"] == []


def test_a_bright_spectrum_is_very_significant():
    wl, f, e = fixture("2mass-0415-0935")
    assert match_spectrum(wl, f, e)["detection_sigma"] > 50.0


def test_min_half_width_widens_the_range_and_the_verdict():
    wl, f, e = fixture("2mass-0415-0935")
    narrow = match_spectrum(wl, f, e)
    wide = match_spectrum(wl, f, e, min_half_width=2)
    assert narrow["type_range"] == ["T7", "T9"] and wide["type_range"] == ["T6", "Y0"]
    assert "T6 to Y0" in wide["verdict"] and wide["best"] == narrow["best"]


def test_a_faint_twin_of_a_t8_is_never_given_a_wrong_type():
    # 2MASS 0415 (T8) 8 times fainter with the noise of a faint field: hardly a point is
    # clear, the fit as a whole is. Each trial is either left undecided or typed with a
    # range that holds T8.
    wl, f, _ = fixture("2mass-0415-0935")
    sigma = np.where(wl > 3.8, 0.11, 0.03)
    labels = ["T5", "T6", "T7", "T8", "T9", "Y0", "Y1"]
    typed = 0
    for seed in range(8):
        noisy = f / 8.0 + np.random.default_rng(seed).normal(0.0, sigma)
        r = match_spectrum(wl, noisy, sigma, min_half_width=2)
        assert r["detection_sigma"] > 10.0
        assert r["class"] in ("brown dwarf", "uncertain")
        if r["class"] == "brown dwarf":
            lo, hi = r["type_range"]
            assert labels.index(lo) <= labels.index("T8") <= labels.index(hi)
            typed += 1
    assert typed >= 1
