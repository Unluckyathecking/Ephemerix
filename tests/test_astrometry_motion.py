"""Parallax, robustness and per-axis errors of `fit_motion` (synthetic data, fixed seeds)."""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import GCRS, SkyCoord
from astropy.time import Time

from pxs.astrometry import CLIP_SIGMA, fit_motion, parallax_factors

RA0, DEC0 = 300.0, -40.0


@pytest.mark.parametrize("ra,dec", [(269.45, 4.69), (330.8, -56.8), (133.8, -7.2)])
def test_parallax_factors_match_astropy(ra: float, dec: float) -> None:
    mjd = np.array([55300.0, 55480.0, 58000.0, 60600.0])
    f_ra, f_dec = parallax_factors(mjd, ra, dec)
    t = Time(mjd, format="mjd")
    plx = 500.0  # mas
    near = SkyCoord(ra * u.deg, dec * u.deg, distance=(1000.0 / plx) * u.pc).transform_to(
        GCRS(obstime=t))
    far = SkyCoord(ra * u.deg, dec * u.deg, distance=1e9 * u.pc).transform_to(GCRS(obstime=t))
    d_ra = (near.ra - far.ra).to_value(u.mas) * np.cos(np.radians(dec))
    d_dec = (near.dec - far.dec).to_value(u.mas)
    assert f_ra * plx == pytest.approx(d_ra, abs=1.0)
    assert f_dec * plx == pytest.approx(d_dec, abs=1.0)


def seasonal(pmra, pmdec, plx, *, noise=0.1, seed=0, start=2010.3, end=2024.3):
    """WISE-like sampling: one visit every six months at fixed times of year, with an extra
    early-season visit so the two seasons are unbalanced."""
    rng = np.random.default_rng(seed)
    years = np.r_[np.arange(start, end + 0.01, 0.5), start + 0.1]
    mjd = 51544.5 + (np.sort(years) - 2000.0) * 365.25
    yr = (mjd - mjd.mean()) / 365.25
    f_ra, f_dec = parallax_factors(mjd, RA0, DEC0)
    e = (pmra * yr + plx * f_ra) / 3.6e6 + rng.normal(0, noise, mjd.size) / 3600
    n = (pmdec * yr + plx * f_dec) / 3.6e6 + rng.normal(0, noise, mjd.size) / 3600
    return mjd, RA0 + e / np.cos(np.radians(DEC0)), DEC0 + n, np.full(mjd.size, noise)


def test_known_parallax_removes_the_seasonal_bias() -> None:
    mjd, ra, dec, err = seasonal(4000.0, -2500.0, 400.0, noise=0.02, seed=1)
    ignored = fit_motion(mjd, ra, dec, err, parallax_mas=0.0)
    fixed = fit_motion(mjd, ra, dec, err, parallax_mas=400.0)
    assert fixed["parallax_model"] == "fixed" and fixed["parallax_mas"] == 400.0
    for key, true in (("pmra_masyr", 4000.0), ("pmdec_masyr", -2500.0)):
        axis_err = fixed["err_pmra_masyr" if key == "pmra_masyr" else "err_pmdec_masyr"]
        assert abs(fixed[key] - true) < 2 * axis_err
    bias = np.hypot(ignored["pmra_masyr"] - 4000.0, ignored["pmdec_masyr"] + 2500.0)
    assert bias > 3 * fixed["err_masyr"]


def test_unknown_parallax_is_fitted_as_a_nuisance_when_there_are_enough_epochs() -> None:
    mjd, ra, dec, err = seasonal(-800.0, 10000.0, 550.0, seed=2)
    m = fit_motion(mjd, ra, dec, err)
    assert m["parallax_model"] == "fitted" and m["parallax_mas"] is None
    assert abs(m["pmra_masyr"] + 800.0) < 2 * m["err_pmra_masyr"]
    assert abs(m["pmdec_masyr"] - 10000.0) < 2 * m["err_pmdec_masyr"]
    few = fit_motion(mjd[:6], ra[:6], dec[:6], err[:6])
    assert few["parallax_model"] == "none"


def test_outlying_epochs_are_rejected_and_reported() -> None:
    mjd, ra, dec, err = seasonal(2000.0, 500.0, 0.0, seed=3)
    dec = dec.copy()
    dec[[5, 17]] += 3.0 / 3600  # two epochs 3" off: a field star taken for the target
    m = fit_motion(mjd, ra, dec, err, parallax_mas=0.0)
    assert m["n_rejected"] == 2 and f"{CLIP_SIGMA:g} sigma" in m["rejected_reason"]
    assert m["n_detections"] == mjd.size - 2
    assert abs(m["pmdec_masyr"] - 500.0) < 2 * m["err_pmdec_masyr"]


def test_rejection_is_capped_when_the_errors_are_simply_too_small() -> None:
    mjd, ra, dec, _ = seasonal(2000.0, 500.0, 0.0, noise=0.5, seed=4)
    m = fit_motion(mjd, ra, dec, np.full(mjd.size, 0.05), parallax_mas=0.0)
    assert m["n_rejected"] <= max(1, int(0.15 * mjd.size))
    assert m["reduced_chi2"] > 10  # and the errors are scaled up instead
    assert abs(m["pmra_masyr"] - 2000.0) < 3 * m["err_pmra_masyr"]


def test_clean_data_reject_nothing_and_give_per_axis_errors() -> None:
    mjd, ra, dec, err = seasonal(100.0, 100.0, 0.0, seed=5)
    m = fit_motion(mjd, ra, dec, err, parallax_mas=0.0)
    assert m["n_rejected"] == 0 and m["rejected_reason"] is None
    assert m["err_masyr"] == max(m["err_pmra_masyr"], m["err_pmdec_masyr"])
    assert 0.3 < m["reduced_chi2"] < 2.5
