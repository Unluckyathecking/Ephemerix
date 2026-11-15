"""Difference cube: each search frame minus a wavelength-matched static-sky reference.

SPHEREx's linear variable filters put every sky pixel at a different wavelength in every
frame, so the reference is matched per grid pixel: the inverse-variance mean of the
reference frames (same detector, other passes) whose wavelength at that pixel is within
MATCH_BANDWIDTHS x the search frame's bandwidth. Pixels with no matching reference are
masked. Residuals of bright stars (PSF and spectral mismatch) are carried as extra
variance, (STAR_RESIDUAL x reference)^2, and pixels where the reference is saturated-
bright are masked.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_dilation

from .layers import Layer

log = logging.getLogger(__name__)

MATCH_BANDWIDTHS = 0.5  # |lambda_ref - lambda| < 0.5 x bandwidth
STAR_RESIDUAL = 0.05  # fractional residual of a static source after subtraction
BRIGHT_MJYSR = 50.0  # reference brighter than this (~ 44 mJy/px peak) is masked
REF_MASK_NSIG = 10.0  # static sources brighter than this in the reference are masked


@dataclass(frozen=True)
class Cube:
    """Difference images of one pass on the field grid, ready for the matched filter.

    diff, var: (n, H, W) float32, MJy/sr and (MJy/sr)^2, NaN where masked. psf: (n, k, k).
    mjd, wave_um (at the field centre), detector: (n,). template: (n,) expected flux of the
    searched spectrum in each frame relative to its value at the reference wavelength.
    """

    diff: np.ndarray
    var: np.ndarray
    psf: np.ndarray
    mjd: np.ndarray
    wave_um: np.ndarray
    detector: np.ndarray
    template: np.ndarray
    masked_fraction: float

    def __len__(self) -> int:
        return int(self.mjd.size)

    def with_template(self, template: np.ndarray) -> Cube:
        return Cube(self.diff, self.var, self.psf, self.mjd, self.wave_um, self.detector,
                    np.asarray(template, float), self.masked_fraction)


def reference_for(layer: Layer, refs: Sequence[Layer]) -> tuple[np.ndarray, np.ndarray]:
    """(reference image, its variance) for one search layer, matched per pixel in wavelength."""
    same = [r for r in refs if r.frame.detector == layer.frame.detector]
    shape = layer.image.shape
    if not same:
        return np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32)
    img = np.stack([r.image for r in same])
    var = np.stack([r.variance for r in same])
    wav = np.stack([r.wave for r in same])
    ok = (np.abs(wav - layer.wave) < MATCH_BANDWIDTHS * layer.band) & np.isfinite(img)
    ok &= np.isfinite(var) & (var > 0)
    w = np.where(ok, 1.0 / np.where(ok, var, 1.0), 0.0)
    ws = w.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(ws > 0, (w * np.where(ok, img, 0.0)).sum(axis=0) / ws, np.nan)
        rvar = np.where(ws > 0, 1.0 / ws, np.nan)
    return mean.astype(np.float32), rvar.astype(np.float32)


def source_mask(ref: np.ndarray) -> np.ndarray:
    """Pixels on static sources bright in the reference (> REF_MASK_NSIG x its sky scatter),
    grown by one pixel. Measured on Haumea's field: stars of G 12-14 leave 10-50% residuals
    (registration, PSF and spectral mismatch between passes), which no variance term can
    stop from stacking, so they are masked instead."""
    v = ref[np.isfinite(ref)]
    if v.size < 100:
        return np.zeros(ref.shape, bool)
    med = float(np.median(v))
    sig = 1.4826 * float(np.median(np.abs(v - med)))
    with np.errstate(invalid="ignore"):
        hot = np.nan_to_num(ref - med) > REF_MASK_NSIG * sig
    return binary_dilation(hot, iterations=1)


def difference_cube(search: Sequence[Layer], refs: Sequence[Layer],
                    template: np.ndarray | None = None) -> Cube:
    """Difference each search layer against its matched reference."""
    if not search:
        raise ValueError("no search layers")
    diffs, vars_ = [], []
    for layer in search:
        ref, rvar = reference_for(layer, refs)
        with np.errstate(invalid="ignore"):
            d = layer.image - ref
            v = layer.variance + rvar + (STAR_RESIDUAL * ref) ** 2
            bad = ~np.isfinite(d) | ~np.isfinite(v) | (v <= 0) | (np.abs(ref) > BRIGHT_MJYSR)
            bad |= source_mask(ref)
        diffs.append(np.where(bad, np.nan, d).astype(np.float32))
        vars_.append(np.where(bad, np.nan, v).astype(np.float32))
    diff = np.stack(diffs)
    n = len(search)
    c = search[0].wave.shape[0] // 2
    return Cube(
        diff=diff, var=np.stack(vars_), psf=np.stack([s.psf for s in search]),
        mjd=np.array([s.mjd for s in search]),
        wave_um=np.array([float(s.wave[c, c]) for s in search]),
        detector=np.array([s.frame.detector for s in search]),
        template=np.ones(n) if template is None else np.asarray(template, float),
        masked_fraction=float(np.mean(~np.isfinite(diff))))
