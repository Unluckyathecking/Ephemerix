"""Probe: the candidate bright-star fixes as patches.

None met the bar (remove the control fields' excess without losing more than a few percent
of injected movers), so none is in pxs.movers; they live here and are applied by
monkeypatching pxs.movers.difference / pxs.movers.core before a run:

    from fix_variants import apply
    apply({"static": True, "halo_scale": 0.5, "ref_weight": "frame"})

static: subtract each detector's per-pixel median difference over the pass.
halo_scale: grow each masked source by halo_scale x its equivalent radius sqrt(area/pi).
ref_weight: "frame" weights reference frames by 1/(frame median variance), not per pixel.
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence

import numpy as np
from scipy import ndimage

STATIC_MIN_FRAMES = 5


def grow_halos(mask: np.ndarray, scale: float) -> np.ndarray:
    """Each connected blob of `mask` widened to a disk of (1 + scale) x its equivalent radius
    about its centroid: brighter sources, with bigger cores, get proportionally bigger halos."""
    if scale <= 0 or not mask.any():
        return mask
    lab, n = ndimage.label(mask)
    area = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    cy, cx = np.array(ndimage.center_of_mass(mask, lab, np.arange(1, n + 1))).T
    out = mask.copy()
    h, w = mask.shape
    for r, y, x in zip((1 + scale) * np.sqrt(area / np.pi), cy, cx):
        y0, y1 = max(int(y - r), 0), min(int(y + r) + 2, h)
        x0, x1 = max(int(x - r), 0), min(int(x + r) + 2, w)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        out[y0:y1, x0:x1] |= np.hypot(yy - y, xx - x) <= r
    return out


def remove_static(diff: np.ndarray, var: np.ndarray, detector: np.ndarray,
                  min_frames: int = STATIC_MIN_FRAMES) -> tuple[np.ndarray, np.ndarray]:
    """(diff, var) with each detector's per-pixel median over the pass subtracted; the
    median's noise, (pi/2) x var / n, is added to the variance."""
    d, v = diff.copy(), var.copy()
    for det in np.unique(detector):
        k = detector == det
        n = np.isfinite(diff[k]).sum(axis=0)
        use = n >= min_frames
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.where(use, np.nanmedian(diff[k], axis=0), 0.0)
            mvar = np.where(use, np.pi / 2 * np.nanmean(var[k], axis=0) / np.maximum(n, 1),
                            0.0)
        d[k] = diff[k] - med[None]
        v[k] = var[k] + mvar[None]
    return d.astype(np.float32), v.astype(np.float32)


def frame_weighted_reference(layer, refs: Sequence, match_bandwidths: float):
    """As difference.reference_for, with one weight per reference frame."""
    same = [r for r in refs if r.frame.detector == layer.frame.detector]
    shape = layer.image.shape
    if not same:
        return np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32)
    img = np.stack([r.image for r in same])
    var = np.stack([r.variance for r in same])
    wav = np.stack([r.wave for r in same])
    ok = (np.abs(wav - layer.wave) < match_bandwidths * layer.band) & np.isfinite(img)
    ok &= np.isfinite(var) & (var > 0)
    typical = np.array([np.median(v[np.isfinite(v) & (v > 0)]) if np.any(
        np.isfinite(v) & (v > 0)) else np.inf for v in var])
    w = np.where(ok, 1.0 / typical[:, None, None], 0.0)
    ws = w.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(ws > 0, (w * np.where(ok, img, 0.0)).sum(axis=0) / ws, np.nan)
        rvar = np.where(ws > 0, (w * w * np.where(ok, var, 0.0)).sum(axis=0) / ws ** 2, np.nan)
    return mean.astype(np.float32), rvar.astype(np.float32)


def apply(opts: dict) -> None:
    """Monkeypatch pxs.movers for one variant (process-wide; call once per process)."""
    import pxs.movers.core as core
    import pxs.movers.difference as dm

    if opts.get("halo_scale", 0.0) > 0:
        plain_mask = dm.source_mask
        scale = float(opts["halo_scale"])
        dm.source_mask = lambda ref: grow_halos(plain_mask(ref), scale)
    if opts.get("ref_weight", "pixel") == "frame":
        dm.reference_for = lambda layer, refs: frame_weighted_reference(
            layer, refs, dm.MATCH_BANDWIDTHS)
    if opts.get("static"):
        plain_cube = dm.difference_cube

        def static_cube(search, refs, template=None):
            c = plain_cube(search, refs, template)
            d, v = remove_static(c.diff, c.var, c.detector)
            return dm.Cube(d, v, c.psf, c.mjd, c.wave_um, c.detector, c.template,
                           c.masked_fraction)

        core.difference_cube = static_cube
