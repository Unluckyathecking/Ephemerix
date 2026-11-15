"""Centroid, rendering and motion fit on recorded real data (tests/fixtures/astro, written by
probes/astro/make_fixtures.py from real WISE and SPHEREx stacks). Offline."""

import json
from pathlib import Path

import numpy as np
import pytest

from pxs import centroid, render
from pxs.astrometry import _tangent_offsets, fit_motion
from pxs.grid import Stack

FIX = Path(__file__).parent / "fixtures" / "astro"
EPOCHS = json.loads((FIX / "motion_epochs.json").read_text())


def load(name: str) -> tuple[Stack, np.ndarray, np.ndarray, dict]:
    z = np.load(FIX / f"{name}.npz")
    m = json.loads(str(z["meta"]))
    mask = z["saturated_mask"] if z["saturated_mask"].size else None
    st = Stack(image=z["image"], mission=m["mission"], band=m["band"],
               wavelength_um=tuple(m["wavelength_um"]), mjd=m["mjd"], date_span_days=0.0,
               n_exposures=10, native_pixscale_arcsec=m["native_pixscale_arcsec"],
               warnings=("saturated",), saturated_mask=mask)
    return st, z["predicted"], z["truth"], m


# Barnard's Star, saturated in every frame. Before: 2010b W2 1.5", 2020b 4.3", 2023a 6.0" off
# (Gaussian on the filled core); W1 2014b not detected (taken for a field star).
@pytest.mark.parametrize("name,tol_arcsec", [
    ("barnards-star-wise-w2-2010b", 0.3), ("barnards-star-wise-w2-2020b", 0.8),
    ("barnards-star-wise-w2-2023a", 0.3), ("barnards-star-wise-w1-2014b", 0.6),
    ("barnards-star-spx-b6-2026a", 1.2)])
def test_barnard_saturated_frames_land_on_gaia_plus_parallax(name: str, tol_arcsec: float) -> None:
    st, pred, truth, m = load(name)
    c, notes = centroid.detect(st, tuple(pred), m["pixscale_arcsec"], 20.0)
    assert c is not None and c.method == "wings", notes
    assert np.hypot(c.x - truth[0], c.y - truth[1]) * m["pixscale_arcsec"] < tol_arcsec
    # and the off-by-one-pixel acceptance: no frame more than about 1 WISE/SPHEREx px off
    assert np.hypot(c.x - truth[0], c.y - truth[1]) * m["pixscale_arcsec"] < \
        m["native_pixscale_arcsec"] / 2


def test_r_draconis_saturated_hole_renders_white() -> None:
    st, pred, _, m = load("r-draconis-spx-b3-2025a")
    assert (~np.isfinite(st.image)).sum() > 1000  # a 60" no-data hole
    px = render.to_uint8(st, render.shared_stretch([st]))
    i, j = int(pred[1]), int(pred[0])
    assert (px[i - 5: i + 6, j - 5: j + 6] == 255).all()
    c = centroid.measure(st, tuple(pred), m["pixscale_arcsec"], 30.0)
    assert c is not None and c.method == "wings"


def _fit(slug: str) -> tuple[dict, dict]:
    d = EPOCHS[slug]
    e = d["epochs"]
    m = fit_motion([x["mjd"] for x in e], [x["ra"] for x in e], [x["dec"] for x in e],
                   [x["err_arcsec"] for x in e], parallax_mas=d["parallax_mas"])
    return m, d


@pytest.mark.parametrize("slug", ["barnards-star", "wise-0855-0714", "2mass-0415-0935"])
def test_measured_motion_agrees_with_published_within_2_sigma(slug: str) -> None:
    m, d = _fit(slug)
    pmra, pmdec = d["published_pm_masyr"]
    assert abs(m["pmra_masyr"] - pmra) < 2 * m["err_pmra_masyr"]
    assert abs(m["pmdec_masyr"] - pmdec) < 2 * m["err_pmdec_masyr"]
    assert 0.3 < m["reduced_chi2"] < 2.5  # the per-epoch errors are about right


def test_epsilon_indi_b_differs_from_its_short_baseline_gaia_motion() -> None:
    # Eps Ind Ba/Bb is an 11-yr binary. Its Gaia DR3 motion (3 yr) includes orbital motion;
    # 16 years of W2 photocentre give a declination motion 40-45 mas/yr more negative, with
    # no outlier, a W2-only fit agreeing, and residuals that drift linearly. Recorded here so a
    # change that "fixes" it is noticed.
    m, d = _fit("epsilon-indi-b")
    assert abs(m["pmra_masyr"] - d["published_pm_masyr"][0]) < 2 * m["err_pmra_masyr"]
    assert -55.0 < m["pmdec_masyr"] - d["published_pm_masyr"][1] < -30.0


def test_barnard_first_to_last_wise_motion_is_the_published_145_5_arcsec() -> None:
    w2 = [e for e in EPOCHS["barnards-star"]["epochs"] if e["id"].startswith("wise-w2")]
    a, b = w2[0], w2[-1]
    xi, eta = _tangent_offsets(np.array([b["ra"]]), np.array([b["dec"]]), a["ra"], a["dec"])
    moved = float(np.degrees(np.hypot(xi, eta))[0] * 3600.0)
    assert (a["id"], b["id"]) == ("wise-w2-2010a", "wise-w2-2024a")
    assert moved == pytest.approx(145.5, abs=1.0)
