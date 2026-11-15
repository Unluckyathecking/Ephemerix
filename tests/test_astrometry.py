import json
from pathlib import Path

import numpy as np
import pytest

from pxs.astrometry import decimal_year, fit_motion, propagate, px_to_sky, sky_to_px, track

TARGETS = json.loads((Path(__file__).parents[1] / "tests/fixtures/astrometry_targets.json").read_text())
MOVING = [t for t in TARGETS if t["pmra_masyr"] is not None]
FOV, SIZE = 240.0, 240


@pytest.mark.parametrize("t", MOVING, ids=lambda t: t["name"])
@pytest.mark.parametrize("year,key", [(2010.5, "pos_2010_5"), (2026.5, "pos_2026_5")])
def test_propagate_matches_validation_targets(t, year, key):
    ra, dec = propagate(t["ra_deg"], t["dec_deg"], t["epoch"], t["pmra_masyr"],
                        t["pmdec_masyr"], year)
    assert ra == pytest.approx(t[key][0], abs=1e-6)
    assert dec == pytest.approx(t[key][1], abs=1e-6)


def test_propagate_zero_dt_is_identity():
    assert propagate(10.0, -5.0, 2016.0, 100.0, -50.0, 2016.0) == (10.0, -5.0)


def test_decimal_year():
    assert decimal_year(51544.5) == pytest.approx(2000.0)
    assert decimal_year(51544.5 + 365.25) == pytest.approx(2001.0)


@pytest.mark.parametrize("dec0", [-57.0, 0.0, 4.7, 66.7])
def test_px_roundtrip(dec0):
    ra0 = 133.0
    x = np.array([0.0, 17.3, 120.0, 239.9])
    y = np.array([239.0, 5.5, 120.0, 61.2])
    ra, dec = px_to_sky(x, y, ra0, dec0, FOV, SIZE)
    x2, y2 = sky_to_px(ra, dec, ra0, dec0, FOV, SIZE)
    np.testing.assert_allclose(x2, x, atol=1e-6)
    np.testing.assert_allclose(y2, y, atol=1e-6)


def test_centre_maps_to_middle():
    assert sky_to_px(10.0, 20.0, 10.0, 20.0, FOV, SIZE) == pytest.approx((120.0, 120.0))


def test_north_is_up_and_east_is_left():
    arcsec = 10 / 3600
    x, y = sky_to_px(50.0, 20.0 + arcsec, 50.0, 20.0, FOV, SIZE)
    assert y < 120 and x == pytest.approx(120.0, abs=1e-6)
    assert y == pytest.approx(110.0, abs=1e-3)  # 1 arcsec per pixel
    x, y = sky_to_px(50.0 + arcsec / np.cos(np.radians(20)), 20.0, 50.0, 20.0, FOV, SIZE)
    assert x < 120 and x == pytest.approx(110.0, abs=1e-2)


def test_cos_dec_near_minus_57_and_ra_wrap():
    # 10 arcsec due east at dec -57 is 10 / cos(dec) arcsec of RA, here across RA = 0
    dec = -57.0
    d_ra = 10 / 3600 / np.cos(np.radians(dec))
    x, y = sky_to_px(d_ra, dec, 0.0, dec, FOV, SIZE)
    assert x == pytest.approx(110.0, abs=0.01)
    ra, _ = px_to_sky(x, y, 0.0, dec, FOV, SIZE)
    assert ra == pytest.approx(d_ra, abs=1e-8)
    x, _ = sky_to_px(360.0 - d_ra, dec, 0.0, dec, FOV, SIZE)
    assert x == pytest.approx(130.0, abs=0.01)  # west of centre: larger x


def test_track_unknown_pm_is_empty():
    tgt = {"ra": 1.0, "dec": 1.0, "epoch": 2016.0, "pmra_masyr": None, "pmdec_masyr": None}
    assert track(tgt, {"ra": 1.0, "dec": 1.0}, FOV, SIZE) == []


def test_track_shape_and_direction():
    t = next(t for t in MOVING if t["name"].startswith("WISE 0855"))
    tgt = {"ra": t["ra_deg"], "dec": t["dec_deg"], "epoch": t["epoch"],
           "pmra_masyr": t["pmra_masyr"], "pmdec_masyr": t["pmdec_masyr"]}
    ra, dec = propagate(t["ra_deg"], t["dec_deg"], t["epoch"], t["pmra_masyr"],
                        t["pmdec_masyr"], 2018.0)
    out = track(tgt, {"ra": ra, "dec": dec}, 400.0, 400, 2010, 2027)
    assert [p["year"] for p in out] == [float(y) for y in range(2010, 2028)]
    assert out[8]["px"] == pytest.approx([200.0, 200.0], abs=1e-3)
    xs = [p["px"][0] for p in out]
    assert xs == sorted(xs)  # moving west (pmra < 0), so x grows
    assert set(out[0]) == {"year", "px"}


def synth_positions(pmra, pmdec, dec0, n=30, noise_as=0.3, seed=0):
    rng = np.random.default_rng(seed)
    mjd = np.sort(rng.uniform(55300, 61100, n))
    yr = (mjd - 58200) / 365.25
    ra = 200.0 + pmra * yr / 3.6e6 / np.cos(np.radians(dec0))
    dec = dec0 + pmdec * yr / 3.6e6
    ra = ra + rng.normal(0, noise_as, n) / 3600 / np.cos(np.radians(dec0))
    dec = dec + rng.normal(0, noise_as, n) / 3600
    return mjd, ra, dec, np.full(n, noise_as)


@pytest.mark.parametrize("dec0", [-57.0, 10.0])
def test_fit_motion_recovers_known_pm(dec0):
    mjd, ra, dec, err = synth_positions(-3000.0, 800.0, dec0, seed=1)
    m = fit_motion(mjd, ra, dec, err)
    assert {"pmra_masyr", "pmdec_masyr", "err_masyr", "baseline_years", "n_detections",
            "err_pmra_masyr", "err_pmdec_masyr", "n_rejected", "parallax_model"} <= set(m)
    assert m["n_detections"] == 30
    assert abs(m["pmra_masyr"] + 3000) < 3 * m["err_masyr"]
    assert abs(m["pmdec_masyr"] - 800) < 3 * m["err_masyr"]
    assert m["baseline_years"] == pytest.approx((mjd.max() - mjd.min()) / 365.25, abs=0.01)


def test_fit_motion_error_is_honest():
    hits, total = 0, 300
    for seed in range(total):
        mjd, ra, dec, err = synth_positions(-3000.0, 800.0, -57.0, n=12, seed=seed)
        m = fit_motion(mjd, ra, dec, err)
        hits += abs(m["pmra_masyr"] + 3000) < m["err_masyr"]
    assert 0.6 < hits / total < 0.9  # about 68% for a 1-sigma error, more as it is the larger axis


def test_fit_motion_inflates_error_when_scatter_exceeds_claim():
    mjd, ra, dec, _ = synth_positions(0.0, 0.0, 0.0, noise_as=2.0, seed=2)
    honest = fit_motion(mjd, ra, dec, np.full(30, 2.0))["err_masyr"]
    claimed = fit_motion(mjd, ra, dec, np.full(30, 0.2))["err_masyr"]
    assert claimed == pytest.approx(honest, rel=0.5)  # the scatter, not the claim, sets the error


def test_fit_motion_degenerate_cases():
    assert fit_motion([55000.0], [1.0], [1.0], [0.1]) is None
    assert fit_motion([55000.0, 55000.0], [1.0, 1.0], [1.0, 1.0], [0.1, 0.1]) is None
    assert fit_motion([55000.0, np.nan], [1.0, 1.0], [1.0, 1.0], [0.1, 0.1]) is None
    two = fit_motion([55000.0, 55365.25], [10.0, 10.0], [0.0, 1.0 / 3600], [0.1, 0.1])
    assert two["pmdec_masyr"] == pytest.approx(1000.0, abs=0.1)
    assert two["pmra_masyr"] == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("dec0", [0.0, 79.0, -79.0])
def test_fit_motion_across_ra_zero(dec0):
    # A mover crossing RA 0: centred on the mean RA (about 180 deg) the fit gave about
    # -1.5e6 mas/yr.
    mjd = np.linspace(55300.0, 61000.0, 20)
    yr = (mjd - mjd[0]) / 365.25
    pmra, pmdec = 3000.0, -500.0
    ra = (359.995 + pmra * yr / 3.6e6 / np.cos(np.radians(dec0))) % 360.0
    dec = dec0 + pmdec * yr / 3.6e6
    assert ra.min() < 1.0 and ra.max() > 359.0
    m = fit_motion(mjd, ra, dec, np.full(20, 0.1))
    # The tangent-plane fit loses a little to curvature over 47" at Dec +-79.
    assert m["pmra_masyr"] == pytest.approx(pmra, rel=0.002)
    assert m["pmdec_masyr"] == pytest.approx(pmdec, abs=5.0)
