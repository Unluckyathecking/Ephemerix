"""One frame resampled onto the field grid: image, variance, wavelength map and PSF kernel.

Reuses pxs.spherex read-only: `frame_layer` (zodi and background subtraction, flags,
normalised resampling) and `psf_model` (the frame's own ePSF at the field centre).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from pxs.grid import Grid, reproject_to_grid
from pxs.spherex import config
from pxs.spherex.photometry import clipped_median, psf_model
from pxs.spherex.read import Stamp
from pxs.spherex.stack import MIN_GOOD_WEIGHT, stamp_half
from pxs.spherex.stamps import read_many
from pxs.spherex.types import Frame

log = logging.getLogger(__name__)

KERNEL_HALF = 7  # PSF kernel is 15x15 grid px (92")
MOVER_BAD_MASK = config.BAD_MASK & ~(1 << config.FLAG_BITS["OUTLIER"])

# Injection hook: (stamp) -> image to add in MJy/sr, same shape as stamp.image, or None.
Injector = Callable[[Stamp], np.ndarray | None]


@dataclass(frozen=True)
class Layer:
    """One frame on the grid. image/variance in MJy/sr and (MJy/sr)^2, NaN where unusable;
    wave/band: um per grid pixel; psf: (15, 15) kernel for a source at a pixel centre, in
    flux fraction per grid pixel."""

    frame: Frame
    mjd: float
    image: np.ndarray
    variance: np.ndarray
    wave: np.ndarray
    band: np.ndarray
    psf: np.ndarray


def field_grid(ra: float, dec: float, size_arcmin: float) -> Grid:
    """Square north-up grid at SPHEREx's native 6.15" pixels, odd number of pixels."""
    n = round(size_arcmin * 60 / config.PIXSCALE_ARCSEC)
    n += 1 - n % 2
    return Grid(ra, dec, n * config.PIXSCALE_ARCSEC, n)


def grid_native_xy(s: Stamp, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """0-based full-frame native pixel (x, y) at each grid pixel centre."""
    yy, xx = np.mgrid[0:grid.size_px, 0:grid.size_px] + 0.5
    ra, dec = grid.wcs().all_pix2world(xx - 0.5, yy - 0.5, 0)
    sx, sy = s.wcs().world_to_pixel_values(ra, dec)
    return sx + s.x0, sy + s.y0


def wave_maps(s: Stamp, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """(wavelength, bandwidth) in um at each grid pixel, bilinear in the WCS-WAVE table."""
    if s.wave_table is None:
        raise ValueError("stamp has no WCS-WAVE table")
    xs, ys, v = (np.asarray(a, float) for a in s.wave_table)
    x, y = grid_native_xy(s, grid)
    xb, yb = x + 1.0, y + 1.0
    ix = np.clip(np.searchsorted(xs, xb) - 1, 0, len(xs) - 2)
    iy = np.clip(np.searchsorted(ys, yb) - 1, 0, len(ys) - 2)
    tx = ((xb - xs[ix]) / (xs[ix + 1] - xs[ix]))[..., None]
    ty = ((yb - ys[iy]) / (ys[iy + 1] - ys[iy]))[..., None]
    out = ((1 - tx) * (1 - ty) * v[iy, ix] + tx * (1 - ty) * v[iy, ix + 1]
           + (1 - tx) * ty * v[iy + 1, ix] + tx * ty * v[iy + 1, ix + 1])
    return out[..., 0].astype(np.float32), out[..., 1].astype(np.float32)


def grid_psf(s: Stamp, grid: Grid) -> np.ndarray:
    """The frame's ePSF for a source at the grid centre, resampled exactly like the data."""
    c = grid.size_px // 2
    ra, dec = grid.wcs().all_pix2world(c, c, 0)
    x, y = s.pixel_of(float(ra), float(dec))
    img = psf_model(s, x, y)
    out = np.nan_to_num(reproject_to_grid(img, s.wcs(), grid))
    k = KERNEL_HALF
    return out[c - k:c + k + 1, c - k:c + k + 1].astype(np.float32)


def mover_good(s: Stamp) -> np.ndarray:
    """Usable pixels for movers: pxs.spherex's BAD_MASK minus OUTLIER. The pipeline sets
    OUTLIER on moving objects: on Haumea's own pixels in 48 of 56 frames of one pass
    (against 8 of 56 at a nearby empty position). Single-frame outliers it would have
    caught (cosmic rays) are clipped along each track instead."""
    finite = np.isfinite(s.image) & np.isfinite(s.variance) & np.isfinite(s.zodi)
    with np.errstate(invalid="ignore"):
        return ((s.flags & MOVER_BAD_MASK) == 0) & finite & (s.variance > 0)


def frame_layer(s: Stamp, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """As pxs.spherex.stack.frame_layer (zodi and background subtracted, normalised
    resampling), but with the mover mask."""
    good = mover_good(s)
    img = s.image - s.zodi
    bkg = clipped_median(img[good]) if good.sum() > 10 else 0.0
    w = s.wcs()
    data = reproject_to_grid(np.where(good, img - bkg, np.nan), w, grid, MIN_GOOD_WEIGHT)
    var = reproject_to_grid(np.where(good, s.variance, np.nan), w, grid, MIN_GOOD_WEIGHT)
    return data, var


def make_layer(frame: Frame, s: Stamp, grid: Grid, inject: Injector | None = None) -> Layer:
    """Grid layer of one stamp, optionally with synthetic sources added to the native image."""
    if inject is not None:
        add = inject(s)
        if add is not None:
            s = dataclasses.replace(s, image=s.image + add)
    data, var = frame_layer(s, grid)
    wave, band = wave_maps(s, grid)
    return Layer(frame, s.mjd, data, var, wave, band, grid_psf(s, grid))


def read_stamps(frames: Sequence[Frame], grid: Grid,
                workers: int = config.MAX_WORKERS) -> list[tuple[Frame, Stamp]]:
    """Field-sized stamps (with ePSF) for each frame; failed or off-field frames are dropped."""
    batch = read_many([(f, grid.center_ra, grid.center_dec) for f in frames],
                      half=stamp_half(grid), with_psf=True, workers=workers)
    if batch.n_failed:
        log.warning("%d of %d frames could not be read", batch.n_failed, len(frames))
    return list(batch.stamps)
