"""Motion fitted on all frames at once (trackfit): synthetic movers, the null cases, and the
recorded W2 visits of CWISE J0411+4714 (tests/fixtures/astro/cwise-0411-4714-w2-visits.npz,
our own stacks of 22 NEOWISE visits, 61x61 px). Offline."""

from pathlib import Path

import numpy as np
import pytest

from pxs import trackfit
from pxs.trackfit import Frames

FIX = Path(__file__).parent / "fixtures" / "astro"
SIGMA = 3.1
YEARS = np.linspace(2010.2, 2024.2, 22)


def _frames(amp: float, xy0=(40.0, 40.0), v=(0.0, 0.0), seed=0, n=80, extra=()) -> Frames:
    """22 noise frames (sigma 1) with a Gaussian source moving at `v` px/yr."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    tau = YEARS - YEARS.mean()
    cube = rng.normal(0.0, 1.0, (YEARS.size, n, n))
    for k, t in enumerate(tau):
        x, y = xy0[0] + v[0] * t, xy0[1] + v[1] * t
        cube[k] += amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA**2))
        for a, ex, ey in extra:
            cube[k] += a * np.exp(-((xx - ex) ** 2 + (yy - ey) ** 2) / (2 * SIGMA**2))
    return Frames(cube, np.ones(cube.shape, bool), np.ones(YEARS.size), YEARS,
                  np.zeros((YEARS.size, 2)))


@pytest.mark.parametrize("v", [(0.45, -0.15), (-0.9, 0.3), (0.0, 0.98)])
def test_recovers_a_mover_that_no_single_frame_shows(v) -> None:
    fr = _frames(amp=0.6, v=v, seed=3)  # matched-filter S/N about 3.3 in each frame
    r = trackfit.fit(fr, SIGMA, (40.4, 39.7), (v[0] * 1.1, v[1] * 0.9))
    assert r is not None and r.n_frames == 22 and r.snr > 8
    assert abs(r.vx - v[0]) < 3 * r.err_v[0] and abs(r.vy - v[1]) < 3 * r.err_v[1]
    assert max(r.err_v) < 0.15  # px/yr


def test_the_seed_motion_does_not_decide_the_answer() -> None:
    fr = _frames(amp=0.6, v=(0.45, -0.15), seed=4)
    right = trackfit.fit(fr, SIGMA, (40.0, 40.0), (0.45, -0.15))
    mirrored = trackfit.fit(fr, SIGMA, (40.0, 40.0), (-0.45, 0.15))
    assert right is not None and mirrored is not None
    assert abs(right.vx - mirrored.vx) < 0.01 and abs(right.vy - mirrored.vy) < 0.01


def test_a_static_source_gets_zero_motion_even_when_seeded_with_one() -> None:
    fr = _frames(amp=0.6, v=(0.0, 0.0), seed=5)
    r = trackfit.fit(fr, SIGMA, (40.0, 40.0), (0.45, -0.15))
    assert r is not None
    assert abs(r.vx) < 3 * r.err_v[0] and abs(r.vy) < 3 * r.err_v[1]


def test_empty_sky_gives_nothing() -> None:
    assert trackfit.fit(_frames(amp=0.0, seed=6), SIGMA, (40.0, 40.0), (0.45, -0.15)) is None


def test_too_few_frames_or_too_short_a_baseline_gives_nothing() -> None:
    fr = _frames(amp=2.0, v=(0.45, -0.15))
    few = Frames(fr.resid[:5], fr.usable[:5], fr.noise[:5], fr.years[:5], fr.shift_px[:5])
    assert trackfit.fit(few, SIGMA, (40.0, 40.0), (0.45, -0.15)) is None
    short = Frames(fr.resid, fr.usable, fr.noise, np.linspace(2020.0, 2023.0, 22), fr.shift_px)
    assert trackfit.fit(short, SIGMA, (40.0, 40.0), (0.45, -0.15)) is None


def test_a_start_off_the_frame_or_at_its_edge_gives_nothing() -> None:
    fr = _frames(amp=2.0, v=(0.45, -0.15))
    for seed in ((500.0, 40.0), (-3.0, 40.0), (40.0, 5.0), (40.0, 79.5)):
        assert trackfit.fit(fr, SIGMA, seed, (0.45, -0.15)) is None


def test_a_source_away_from_the_predicted_place_is_not_taken() -> None:
    fr = _frames(amp=0.0, extra=[(3.0, 47.0, 40.0)], seed=7)  # only a neighbour 7 px off
    assert trackfit.fit(fr, SIGMA, (40.0, 40.0), (0.45, -0.15)) is None


def test_a_modelled_neighbour_does_not_shift_the_motion() -> None:
    v = (0.0, 0.98)
    fr = _frames(amp=0.6, v=v, seed=8, extra=[(0.9, 49.0, 40.0)])  # 1.5x brighter, 9 px away
    r = trackfit.fit(fr, SIGMA, (40.0, 40.0), v, static=[(49.0, 40.0)])
    assert r is not None
    assert abs(r.vx - v[0]) < 3 * r.err_v[0] and abs(r.vy - v[1]) < 3 * r.err_v[1]


def test_inputs_are_not_changed() -> None:
    fr = _frames(amp=0.6, v=(0.45, -0.15))
    before = fr.resid.copy()
    trackfit.fit(fr, SIGMA, (40.0, 40.0), (0.45, -0.15))
    assert np.array_equal(fr.resid, before)


# --- recorded visits of CWISE J0411+4714 ---------------------------------------------------


def _recorded():
    z = np.load(FIX / "cwise-0411-4714-w2-visits.npz")
    resid = z["resid"].astype(float)
    fr = Frames(resid, np.ones(resid.shape, bool), z["noise"], z["years"],
                np.zeros((z["years"].size, 2)))
    kw = {"static": [tuple(s) for s in z["static"]], "half": int(z["half"]),
          "inflate": float(z["inflate"])}
    return fr, float(z["sigma_px"]), tuple(z["seed"]), tuple(z["velocity"]), kw


def test_recorded_target_moves_and_the_answer_is_the_same_from_any_start() -> None:
    fr, sigma, seed, v, kw = _recorded()
    r = trackfit.fit(fr, sigma, seed, v, **kw)
    assert r is not None and r.snr > 20
    # 1"/px: mas/yr = -1000 * px/yr. Recorded on 15 Nov 2026: (+387, -161) mas/yr.
    assert -1000 * r.vx == pytest.approx(387.0, abs=15.0)
    assert -1000 * r.vy == pytest.approx(-161.0, abs=15.0)
    assert 30.0 < 1000 * max(r.err_v) < 60.0
    for start in ((0.0, 0.0), (-v[0], -v[1])):
        other = trackfit.fit(fr, sigma, seed, start, **kw)
        assert other is not None
        assert abs(other.vx - r.vx) < 0.01 and abs(other.vy - r.vy) < 0.01


def test_recorded_target_fits_worse_with_the_visits_in_any_shuffled_order() -> None:
    fr, sigma, seed, v, kw = _recorded()
    true = trackfit.fit(fr, sigma, seed, v, **kw)
    rng = np.random.default_rng(11)
    for _ in range(12):
        years = fr.years[rng.permutation(fr.years.size)]
        shuffled = Frames(fr.resid, fr.usable, fr.noise, years, fr.shift_px)
        r = trackfit.fit(shuffled, sigma, seed, v, **kw)
        assert r is None or r.reduced_chi2 > true.reduced_chi2 * 1.05


def test_recorded_static_neighbour_has_no_motion() -> None:
    fr, sigma, _, _, kw = _recorded()
    # CatWISE J041103.49+471431.5 (W2 14.47), 13" from the target's mid-track position
    star = min(kw["static"], key=lambda s: np.hypot(s[0] - 21.4, s[1] - 20.6))
    others = [s for s in kw["static"] if s != star]
    r = trackfit.fit(fr, sigma, star, (0.3, 0.3), static=others, half=kw["half"],
                     inflate=kw["inflate"])
    assert r is not None
    assert abs(r.vx) < 3 * r.err_v[0] and abs(r.vy) < 3 * r.err_v[1]
