"""Forced ePSF photometry on one stamp, and the empirical error scale from empty positions.

Recipe: subtract ZODI, subtract a sigma-clipped
background from a 6-10 px annulus, fit amplitude x ePSF at the given sub-pixel position to
good pixels within 3 px weighted by 1/VARIANCE, convert MJy/sr to mJy with the nominal
pixel solid angle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from . import config
from .read import Stamp

# Empty positions used to measure the real noise: 8 px away in a ring of 8.
OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dx, dy) for dx in (-8, 0, 8) for dy in (-8, 0, 8) if (dx, dy) != (0, 0))


@dataclass(frozen=True)
class Phot:
    """Flux and 1-sigma error in mJy (NaN when not measured) and why it was not."""

    flux_mjy: float
    err_mjy: float
    reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.reason


def good_mask(s: Stamp) -> np.ndarray:
    """Pixels usable for photometry: no BAD_MASK bit (SOURCE is never masked), all finite."""
    finite = np.isfinite(s.image) & np.isfinite(s.variance) & np.isfinite(s.zodi)
    with np.errstate(invalid="ignore"):
        return ((s.flags & config.BAD_MASK) == 0) & finite & (s.variance > 0)


def radius(s: Stamp, x: float, y: float) -> np.ndarray:
    """Distance in px of each stamp pixel from full-frame position (x, y)."""
    yy, xx = np.mgrid[0:s.image.shape[0], 0:s.image.shape[1]]
    return np.hypot(xx + s.x0 - x, yy + s.y0 - y)


def clipped_median(values: np.ndarray, nsig: float = 3.0) -> float:
    """Median after one 3-sigma clip about the median (sigma from the MAD)."""
    med = float(np.median(values))
    mad = 1.4826 * float(np.median(np.abs(values - med)))
    if mad <= 0:
        return med
    return float(np.median(values[np.abs(values - med) < nsig * mad]))


def bilinear(a: np.ndarray, y: np.ndarray, x: np.ndarray, fill: float) -> np.ndarray:
    """Bilinear sample of 2-D `a` at fractional (y, x); `fill` outside."""
    ny, nx = a.shape
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    tx, ty = x - x0, y - y0
    inside = (x0 >= 0) & (y0 >= 0) & (x0 < nx - 1) & (y0 < ny - 1)
    xc, yc = np.clip(x0, 0, nx - 2), np.clip(y0, 0, ny - 2)
    v = ((1 - tx) * (1 - ty) * a[yc, xc] + tx * (1 - ty) * a[yc, xc + 1]
         + (1 - tx) * ty * a[yc + 1, xc] + tx * ty * a[yc + 1, xc + 1])
    return np.where(inside, v, fill)


def psf_model(s: Stamp, x: float, y: float) -> np.ndarray:
    """The stamp's ePSF (sums to ~1) sampled at stamp pixels for a source at (x, y)."""
    if s.psf is None:
        raise ValueError("stamp has no EPSF")
    yy, xx = np.mgrid[0:s.image.shape[0], 0:s.image.shape[1]]
    o, c = config.EPSF_OVERSAMPLE, (config.EPSF_SIZE - 1) / 2
    return bilinear(s.psf, c + o * (yy + s.y0 - y), c + o * (xx + s.x0 - x), 0.0) * o * o


def core_reason(s: Stamp, r: np.ndarray) -> str:
    core = r <= config.R_CORE
    if np.any(s.flags[core] & config.MISSING_MASK):
        return "masked"
    if np.any(s.flags[core] & config.SATURATION_MASK) or not np.all(np.isfinite(s.image[core])):
        return "saturated"
    return ""


def measure(s: Stamp, dx: float = 0.0, dy: float = 0.0) -> Phot:
    """PSF-fit flux at the stamp's target position shifted by (dx, dy) px."""
    x, y = s.xpix + dx, s.ypix + dy
    r = radius(s, x, y)
    reason = core_reason(s, r)
    if reason:
        return Phot(np.nan, np.nan, reason)
    if s.psf is None or not np.any(s.psf):
        return Phot(np.nan, np.nan, "no psf")
    good = good_mask(s)
    img = s.image - s.zodi
    ann = good & (r >= config.R_ANNULUS[0]) & (r < config.R_ANNULUS[1])
    if ann.sum() < 10:
        return Phot(np.nan, np.nan, "no background")
    bkg = clipped_median(img[ann])
    fit = r <= config.R_FIT
    use = fit & good
    p = psf_model(s, x, y)
    if use.sum() < 4 or p[use].sum() < config.MIN_PSF_FRACTION * p[fit].sum():
        return Phot(np.nan, np.nan, "masked")
    w = 1.0 / s.variance[use]
    pp = p[use]
    den = float(np.sum(w * pp * pp))
    amp = float(np.sum(w * pp * (img[use] - bkg))) / den
    return Phot(amp * config.MJYSR_TO_MJY, float(config.MJYSR_TO_MJY / np.sqrt(den)))


def measured_error_scale(stamps: Sequence[Stamp], min_samples: int = 20) -> float | None:
    """Factor (>= 1) to multiply variance-based errors by, from empty-position scatter.

    Robust sigma (1.4826 x MAD) of flux/err over every stamp at the 8 OFFSETS, or None
    when there are fewer than `min_samples` measurements.
    """
    z = [m.flux_mjy / m.err_mjy for s in stamps for dx, dy in OFFSETS
         if (m := measure(s, dx, dy)).ok and m.err_mjy > 0]
    if len(z) < min_samples:
        return None
    a = np.asarray(z)
    sigma = 1.4826 * float(np.median(np.abs(a - np.median(a))))
    return max(1.0, sigma)


def error_scale(stamps: Sequence[Stamp], min_samples: int = 20) -> float:
    """measured_error_scale, or config.ERROR_SCALE when too few samples to measure it."""
    scale = measured_error_scale(stamps, min_samples)
    return config.ERROR_SCALE if scale is None else scale
