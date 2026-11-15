"""Checks of the numpy parts (not collected by the repository's default pytest run):

    uv run pytest tools/denoise -q

The model's blind spot is checked where torch exists: `model.blind_check` runs at the start
of training and whenever a gate container loads a checkpoint.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import numpy as np

from denoise import analyze
from denoise.features import CHANNELS, N_SCALARS, build
from pxs.movers.difference import difference_cube

H = 41


def _layer(rng: np.random.Generator, det: int, wave0: float, mjd: float) -> NS:
    img = rng.normal(0, 1, (H, H)).astype(np.float32)
    img[5, 5] = np.nan
    wave = (wave0 + np.linspace(0, 0.01, H)[None] * np.ones((H, 1))).astype(np.float32)
    psf = np.zeros((15, 15), np.float32)
    psf[7, 7] = 1.0
    return NS(frame=NS(detector=det), mjd=mjd, image=img, variance=np.ones((H, H), np.float32),
              wave=wave, band=np.full((H, H), 0.03, np.float32), psf=psf)


def test_features_reproduce_the_difference_image() -> None:
    rng = np.random.default_rng(1)
    search = [_layer(rng, 1, 0.9, 1.0), _layer(rng, 2, 1.3, 2.0)]
    refs = [_layer(rng, 1, 0.9 + 0.004 * k, 100.0 + k) for k in range(6)]
    cube = difference_cube(search, refs)
    x, scal, sig, rvar = build(search, refs, cube)
    assert x.shape == (2, len(CHANNELS), H, H) and scal.shape == (2, N_SCALARS)
    assert np.isfinite(x).all()
    ok = x[0, 1] > 0
    assert ok.mean() > 0.9 and not x[1, 1].any()  # detector 2 has no reference
    np.testing.assert_allclose((x[0, 0] * sig[0])[ok], cube.diff[0][ok], rtol=1e-4, atol=1e-5)
    assert np.all(rvar[0][ok] < cube.var[0][ok])
    assert abs(1.4826 * np.median(np.abs(x[0, 0][ok] - np.median(x[0, 0][ok]))) - 1) < 1e-3


def test_search_frame_enters_only_the_blind_channels() -> None:
    rng = np.random.default_rng(2)
    search = [_layer(rng, 1, 0.9, 1.0)]
    refs = [_layer(rng, 1, 0.9 + 0.004 * k, 100.0 + k) for k in range(6)]
    x0, _, _, _ = build(search, refs, difference_cube(search, refs))
    search[0].image[20, 20] += 0.5  # a faint source in the search frame only
    x1, _, _, _ = build(search, refs, difference_cube(search, refs))
    changed = np.abs(x1 - x0).max(axis=(1, 2, 3))[0]
    assert changed > 0
    # Only t differs, and away from the source only through the frame's robust scale.
    np.testing.assert_array_equal(x1[0, 1:], x0[0, 1:])
    far = np.ones((H, H), bool)
    far[20, 20] = False
    assert np.abs(x1[0, 0] - x0[0, 0])[far].max() < 0.02


def test_matched_threshold_never_raises_the_false_alarm_count() -> None:
    base = np.array([5.2, 6.0, 7.1, 9.0])
    n0, t = analyze.matched_threshold(base, np.array([5.1, 5.3, 6.4, 6.6, 8.0]))
    assert n0 == 2 and t == 6.45  # two den peaks (6.6, 8.0) remain at 6.45; three at 6.40
    n0, t = analyze.matched_threshold(base, np.array([7.5, 8.0, 9.0]))
    assert n0 == 2 and t == 7.55  # more null peaks after "denoising": threshold goes up


def test_flux_gate_flags_a_shift() -> None:
    rng = np.random.default_rng(0)

    def data(shift: float) -> dict:
        src = []
        for _ in range(400):
            f = float(np.exp(rng.uniform(np.log(0.02), np.log(0.4))))
            fb = f + rng.normal(0, 0.01)
            src.append({"flux_mjy": f, "base": {"forced": fb, "forced_err": 0.01},
                        "den": {"forced": fb - shift * f, "forced_err": 0.01}})
        return {"A": {"src": src}}

    assert analyze.gate2(data(0.0))["pass"]
    assert analyze.gate2(data(0.005))["pass"]  # under the 1% allowance
    assert not analyze.gate2(data(0.03))["pass"]
