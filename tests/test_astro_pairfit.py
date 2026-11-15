"""Joint fit of the target and a neighbour: synthetic pairs, and pairs planted in a recorded
real W2 frame (tests/fixtures/astro/cwise-1055-5443-wise-w2-2021a-field.npz, our own stack of
one NEOWISE visit). Offline."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pxs import centroid, fitblend, pairfit
from pxs.grid import Stack

FIX = Path(__file__).parent / "fixtures" / "astro"
SIGMA = 3.1  # W2 PSF sigma on the 1"/px grid
HALF = 11


def _scene(sources, n=120, noise=1.0, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    img = rng.normal(0.0, noise, (n, n))
    for amp, x, y in sources:
        img = img + amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA**2))
    return img


def _fit(img, target, neighbours, **kw):
    return pairfit.fit(img, np.ones(img.shape, bool), 1.0, SIGMA, HALF, target, neighbours,
                       max_shift_px=7.3, **kw)


@pytest.mark.parametrize("sep,ratio", [(9.0, 0.6), (10.0, 1.0), (14.0, 1.2)])
def test_joint_fit_recovers_both_positions(sep: float, ratio: float) -> None:
    img = _scene([(40.0, 60.3, 60.7), (40.0 * ratio, 60.3, 60.7 - sep)])
    r = _fit(img, (60.5, 60.5), [(60.5, 60.5 - sep)])
    assert r is not None
    assert np.hypot(r.x - 60.3, r.y - 60.7) < 0.15
    assert np.hypot(r.neighbours[0][0] - 60.3, r.neighbours[0][1] - (60.7 - sep)) < 0.3
    assert 0.0 < r.sx < 0.2 and 0.0 < r.sy < 0.2


def test_no_neighbour_means_no_joint_fit() -> None:
    assert _fit(_scene([(40.0, 60.3, 60.7)]), (60.5, 60.5), []) is None


def test_refused_when_the_neighbour_is_not_there() -> None:
    # seeded on empty sky: the second Gaussian has nothing to fit
    img = _scene([(40.0, 60.3, 60.7)])
    assert _fit(img, (60.5, 60.5), [(60.5, 45.5)]) is None


def test_refused_when_too_close_or_much_brighter() -> None:
    close = _scene([(40.0, 60.3, 60.7), (30.0, 60.3, 54.7)])
    assert _fit(close, (60.5, 60.5), [(60.5, 54.5)], min_sep_px=8.0) is None
    bright = _scene([(40.0, 60.3, 60.7), (200.0, 60.3, 48.7)])
    assert _fit(bright, (60.5, 60.5), [(60.5, 48.5)]) is None


def test_inputs_are_not_changed() -> None:
    img = _scene([(40.0, 60.3, 60.7), (30.0, 60.3, 50.7)])
    before, ok = img.copy(), np.ones(img.shape, bool)
    pairfit.fit(img, ok, 1.0, SIGMA, HALF, (60.5, 60.5), [(60.5, 50.5)], 7.3)
    assert np.array_equal(img, before) and ok.all()


# --- pairs planted in a real frame ---------------------------------------------------------


def _real_frame():
    z = np.load(FIX / "cwise-1055-5443-wise-w2-2021a-field.npz")
    m = json.loads(str(z["meta"]))
    st = Stack(image=z["image"], mission=m["mission"], band=m["band"],
               wavelength_um=tuple(m["wavelength_um"]), mjd=m["mjd"], date_span_days=0.0,
               n_exposures=10, native_pixscale_arcsec=m["native_pixscale_arcsec"])
    return st, centroid._prepare(st, m["pixscale_arcsec"])


def _isolated(fr, lo=7.0, hi=40.0, gap=24.0, edge=36.0):
    ny, nx = fr.snr.shape
    pk = centroid._peaks(fr, (nx / 2, ny / 2), nx, 4.0)
    return [p for p in pk if lo <= p[2] <= hi and edge < p[0] < nx - edge
            and edge < p[1] < ny - edge
            and all(q is p or np.hypot(q[0] - p[0], q[1] - p[1]) >= gap for q in pk)]


def _planted_bias(st, fr, star, sep: int, ratio: float):
    """Shift of the single and joint fits towards a planted neighbour, per direction. The
    neighbour is a scaled copy of the whole frame moved by `sep` px: real PSF, real noise.
    As in `detect`, the candidate is the blended frame's peak nearest the star."""
    truth = centroid._fit(fr, star)
    single, joint = [], []
    for dx, dy in ((sep, 0), (0, sep), (-sep, 0), (0, -sep)):
        img = fr.resid + ratio * np.roll(fr.resid, (dy, dx), axis=(0, 1))
        fr2 = replace(fr, resid=img, snr=centroid._snr_map(img, fr.usable, fr.sigma_px))
        peaks = centroid._peaks(fr2, star, 15.0, centroid.SNR_MIN)
        if not peaks:
            continue
        peak, u = peaks[0], np.array([dx, dy]) / sep
        one = centroid._fit(fr2, peak)
        two = centroid._measure_peak(fr2, peak, st, 1.0, [(star[0] + dx, star[1] + dy)])
        if one is not None:
            single.append(float(np.dot([one[0] - truth[0], one[1] - truth[1]], u)))
        if two is not None and two[4]:
            joint.append(float(np.dot([two[0] - truth[0], two[1] - truth[1]], u)))
    return single, joint


@pytest.mark.parametrize("sep,ratio,single_min", [(9, 0.6, 0.5), (10, 0.6, 0.3), (10, 1.0, 1.0),
                                                  (12, 1.0, 0.1), (16, 0.6, -0.1)])
def test_planted_neighbour_in_a_real_frame(sep: int, ratio: float, single_min: float) -> None:
    st, fr = _real_frame()
    stars = _isolated(fr)
    assert len(stars) >= 4, len(stars)
    single, joint = [], []
    for s in stars:
        a, b = _planted_bias(st, fr, s, sep, ratio)
        single += a
        joint += b
    assert len(joint) >= 0.6 * len(single)  # the joint fit is used in most cases
    assert abs(np.median(joint)) < 0.25  # arcsec (1"/px): no pull towards the neighbour
    assert np.median(single) >= single_min  # the single fit is pulled, as on the real target


# --- wiring: centroid.detect and fitblend --------------------------------------------------


def test_detect_notes_the_joint_fit_and_fitblend_keeps_the_frame() -> None:
    st, fr = _real_frame()
    star = max(_isolated(fr), key=lambda p: p[2])
    img = st.image + 0.6 * np.roll(fr.resid, (0, 10), axis=(0, 1)).astype(st.image.dtype)
    st2 = replace(st, image=img)
    alone, _ = centroid.detect(st, (star[0], star[1]), 1.0, 15.0)
    c, _ = centroid.detect(st2, (star[0], star[1]), 1.0, 15.0,
                           neighbours_px=[(star[0] + 10, star[1])])
    assert c is not None and any(w.startswith(centroid.JOINT) for w in c.warnings)
    assert np.hypot(c.x - alone.x, c.y - alone.y) < 0.6
    assert not any(w.startswith(centroid.JOINT) for w in alone.warnings)
    frame = {"centroid_px": [c.x, c.y], "warnings": list(c.warnings)}
    assert fitblend.jointly_fitted(frame)


def test_spherex_frames_are_not_jointly_fitted() -> None:
    st, fr = _real_frame()
    star = max(_isolated(fr), key=lambda p: p[2])
    img = st.image + 0.6 * np.roll(fr.resid, (0, 10), axis=(0, 1)).astype(st.image.dtype)
    spx = replace(st, image=img, mission="SPHEREx", band="spx-b6", wavelength_um=(4.4, 5.0),
                  native_pixscale_arcsec=6.15)
    c, _ = centroid.detect(spx, (star[0], star[1]), 1.0, 15.0,
                           neighbours_px=[(star[0] + 10, star[1])])
    assert c is None or not any(w.startswith(centroid.JOINT) for w in c.warnings)
