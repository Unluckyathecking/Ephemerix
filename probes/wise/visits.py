"""Group L1b frames into visits and stack each visit onto one north-up grid.

  group_visits(frames)                -> list[list[Frame]]
  north_up_grid(ra, dec, arcmin)      -> WCS
  stack_visit(stamps, grid)           -> VisitStack

Rejection, in order:
  1. header: Moon closer than MOON_MIN_DEG (scattered light);
  2. geometry: stamp covers < MIN_COVER of the grid (frame edge);
  3. noise: robust background noise > NOISE_FACTOR x the visit median (bad or streaked frames);
  4. per pixel: 3-sigma clip across frames (cosmic rays, satellite glints, latents), then mean.
Saturated pixels are NaN in the L1b int image. Where every frame is NaN but the grid is
covered, the pixel is flagged saturated and filled with the stack maximum, so bright stars
show a solid core instead of a hole.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clip
from astropy.time import Time
from astropy.wcs import WCS
from reproject import reproject_interp

from l1b_bucket import Frame, Stamp

VISIT_GAP_DAYS = 20.0
LONG_VISIT_DAYS = 60.0  # near the ecliptic poles coverage is continuous: split by half-year
PIX_ARCSEC = 2.75
MOON_MIN_DEG = 12.0
MIN_COVER = 0.9
NOISE_FACTOR = 2.0


@dataclass(frozen=True)
class VisitStack:
    image: np.ndarray
    mjd: float
    n_avail: int
    n_used: int
    rejected: dict
    noise: float  # robust background sigma of the stack
    n_saturated: int


def group_visits(frames: list[Frame]) -> list[list[Frame]]:
    frames = sorted(frames, key=lambda f: f.mjd)
    groups: list[list[Frame]] = []
    for f in frames:
        if groups and f.mjd - groups[-1][-1].mjd <= VISIT_GAP_DAYS:
            groups[-1].append(f)
        else:
            groups.append([f])
    out: list[list[Frame]] = []
    for g in groups:
        if g[-1].mjd - g[0].mjd <= LONG_VISIT_DAYS:
            out.append(g)
            continue
        halves: dict[int, list[Frame]] = {}
        for f in g:
            halves.setdefault(int(Time(f.mjd, format="mjd").decimalyear * 2), []).append(f)
        out.extend(halves[k] for k in sorted(halves))
    return out


def north_up_grid(ra: float, dec: float, arcmin: float) -> WCS:
    n = int(round(arcmin * 60 / PIX_ARCSEC)) | 1
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIX_ARCSEC / 3600, PIX_ARCSEC / 3600]
    w.pixel_shape = (n, n)
    return w


def robust_sigma(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(1.4826 * np.median(np.abs(a - np.median(a)))) if a.size else np.inf


def _resample(stamp: Stamp, grid: WCS) -> tuple[np.ndarray, np.ndarray]:
    shape = grid.pixel_shape[::-1]
    img, _ = reproject_interp((stamp.data, stamp.wcs), grid, shape_out=shape)
    cover, _ = reproject_interp((np.ones_like(stamp.data), stamp.wcs), grid, shape_out=shape)
    covered = np.nan_to_num(cover) > 0.99
    return img - np.nanmedian(img[covered]), covered


def stack_visit(stamps: list[Stamp], grid: WCS, n_avail: int) -> VisitStack:
    rejected = {"moon": 0, "edge": 0, "noise": 0}
    layers, covers, mjds = [], [], []
    for s in stamps:
        if s.header.get("MOONSEP", 180.0) < MOON_MIN_DEG:
            rejected["moon"] += 1
            continue
        img, covered = _resample(s, grid)
        if covered.mean() < MIN_COVER:
            rejected["edge"] += 1
            continue
        layers.append(img)
        covers.append(covered)
        mjds.append(s.frame.mjd)
    shape = grid.pixel_shape[::-1]
    if not layers:
        return VisitStack(np.full(shape, np.nan), np.nan, n_avail, 0, rejected, np.inf, 0)
    noise = np.array([robust_sigma(x) for x in layers])
    keep = noise <= NOISE_FACTOR * np.median(noise)
    rejected["noise"] = int((~keep).sum())
    cube = np.array(layers)[keep]
    image = sigma_clip(cube, sigma=3, axis=0, masked=True).mean(axis=0).filled(np.nan)
    saturated = np.any(np.array(covers)[keep], axis=0) & ~np.isfinite(image)
    if saturated.any():
        image[saturated] = np.nanmax(image)
    return VisitStack(image=image, mjd=float(np.mean(np.array(mjds)[keep])), n_avail=n_avail,
                      n_used=int(keep.sum()), rejected=rejected, noise=robust_sigma(image),
                      n_saturated=int(saturated.sum()))
