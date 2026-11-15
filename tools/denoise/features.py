"""Model inputs and target for one pass of one field, from the pipeline's own layers.

The target is the pipeline's difference image (pxs.movers.difference.difference_cube),
whitened per pixel by its own variance. The inputs are of two kinds, kept apart because the
model treats them differently:

* reference channels, built only from other passes (>= 60 days away, so a mover is not in
  them at the same sky position): the wavelength-matched reference, a deep all-wavelength
  reference, the wavelength offset of the matched reference, the reference noise, and
  whether a reference exists;
* blind channels, from the search frame itself (the whitened difference and its valid
  mask), which the model may only read outside a hole around the pixel it predicts.

Nothing derived from the search frame's own variance is given outside the blind channels:
the Level 2 variance carries the photon noise of sources, which would tell the model about
a source at the predicted pixel. Numpy only; the same function feeds training and the gate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

CHANNELS = ("t", "m", "ref", "deep", "dlam", "lrv", "rm")
BLIND = (0, 1)  # channel indices the model may only see outside the hole
REF = (2, 3, 4, 5, 6)
N_SCALARS = 6
T_CLIP = 50.0  # whitened values beyond this are clipped in the inputs (not in the data)


def _ref_stats(layer: Any, same: tuple[np.ndarray, np.ndarray, np.ndarray] | None
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(matched reference, its variance, matched wavelength offset in bandwidths, deep
    reference) for one search layer. The first two repeat difference.reference_for."""
    from pxs.movers.difference import MATCH_BANDWIDTHS

    shape = layer.image.shape
    nan = np.full(shape, np.nan, np.float32)
    if same is None:
        return nan, nan, nan, nan
    img, var, wav = same
    good = np.isfinite(img) & np.isfinite(var) & (var > 0)
    w_all = np.where(good, 1.0 / np.where(good, var, 1.0), 0.0)
    w = np.where(np.abs(wav - layer.wave) < MATCH_BANDWIDTHS * layer.band, w_all, 0.0)
    ws, wa = w.sum(axis=0), w_all.sum(axis=0)
    val = np.where(good, img, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ref = np.where(ws > 0, (w * val).sum(axis=0) / ws, np.nan)
        rvar = np.where(ws > 0, 1.0 / ws, np.nan)
        dlam = np.where(ws > 0, ((w * wav).sum(axis=0) / ws - layer.wave) / layer.band, np.nan)
        deep = np.where(wa > 0, (w_all * val).sum(axis=0) / wa, np.nan)
    return ref, rvar, dlam, deep


def _psf_scalars(psf: np.ndarray) -> tuple[float, float]:
    """Peak pixel fraction and rms radius (px) of a PSF kernel."""
    p = np.clip(psf, 0, None)
    tot = float(p.sum())
    if tot <= 0:
        return 0.0, 0.0
    k = psf.shape[0] // 2
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    return float(p.max() / tot), float(np.sqrt((p * (xx ** 2 + yy ** 2)).sum() / tot))


def build(search: Sequence[Any], refs: Sequence[Any], cube: Any
          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(x, scal, sig, rvar): x (n, 7, H, W) float32 in CHANNELS order, scal (n, N_SCALARS),
    rvar (n, H, W) the matched reference's variance (the part of cube.var it adds), and
    sig (n, H, W), the factor that undoes the whitening: diff = t x sig (sqrt(cube.var) times
    the frame's robust scale; NaN where masked).
    `cube` must be difference_cube(search, refs)."""
    by_det: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for det in {r.frame.detector for r in refs}:
        rs = [r for r in refs if r.frame.detector == det]
        by_det[det] = (np.stack([r.image for r in rs]), np.stack([r.variance for r in rs]),
                       np.stack([r.wave for r in rs]))
    n = len(search)
    h, w = search[0].image.shape
    x = np.zeros((n, len(CHANNELS), h, w), np.float32)
    scal = np.zeros((n, N_SCALARS), np.float32)
    sig = np.sqrt(cube.var).astype(np.float32)
    rvars = np.full((n, h, w), np.nan, np.float32)
    for i, layer in enumerate(search):
        ref, rvar, dlam, deep = _ref_stats(layer, by_det.get(layer.frame.detector))
        rvars[i] = rvar
        ok = np.isfinite(cube.diff[i]) & np.isfinite(sig[i]) & (sig[i] > 0)
        s0 = float(np.median(sig[i][ok])) if ok.any() else 1.0
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(ok, cube.diff[i] / np.where(ok, sig[i], 1.0), 0.0)
            lrv = np.log(np.sqrt(rvar) / s0)
        # The pipeline variance is off by a frame-dependent factor (matched.py rescales it
        # the same way), so each frame's whitened image is brought to unit robust scatter.
        scale = 1.4826 * float(np.median(np.abs(t[ok] - np.median(t[ok])))) if ok.any() else 1.0
        scale = scale if scale > 0 else 1.0
        t, sig[i] = t / scale, sig[i] * scale
        x[i, 0] = np.clip(t, -T_CLIP, T_CLIP)
        x[i, 1] = ok
        x[i, 2] = np.nan_to_num(np.arcsinh(ref / s0))
        x[i, 3] = np.nan_to_num(np.arcsinh(deep / s0))
        x[i, 4] = np.clip(np.nan_to_num(dlam), -1, 1)
        x[i, 5] = np.clip(np.nan_to_num(lrv, neginf=-4.0, posinf=4.0), -4, 4)
        x[i, 6] = np.isfinite(ref)
        det = int(layer.frame.detector)
        peak, rad = _psf_scalars(layer.psf)
        scal[i] = [(float(cube.wave_um[i]) - 1.6) / 0.8, det == 1, det == 2, det == 3, peak,
                   rad / 2.0]
    return x, scal, sig, rvars
