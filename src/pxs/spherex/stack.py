"""Fixed-sky image stack of one pass in one wavelength window, for the blink."""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Sequence

import numpy as np
from astropy.wcs import WCS

from pxs.grid import Grid, Stack

from . import config
from .net import BlockStore
from .photometry import clipped_median, core_reason, good_mask, radius
from .read import Stamp
from .stamps import position_at, read_many
from .types import Pass, Target

log = logging.getLogger(__name__)

REJECT_NSIG = 5.0  # per-pixel outlier cut across frames
MIN_FRAMES_TO_REJECT = 3
# Share of a stack's frames that must be saturated at the target before the stack is called
# saturated. One OVERFLOW pixel in 1 of 41 Eps Ind B frames (likely a cosmic ray; the star
# peaks far below saturation) flagged the whole 4.2-5.0 um stack; Barnard is 11 of 12.
SATURATED_SHARE = 0.25
MIN_GOOD_WEIGHT = 0.5  # share of a grid pixel's interpolation weight that must be good


def check_window(window_um: tuple[float, float]) -> tuple[float, float]:
    """(lo, hi) in um as floats; ValueError unless finite with 0.5 <= lo < hi <= 5.5."""
    lo, hi = (float(v) for v in window_um)
    if not (math.isfinite(lo) and math.isfinite(hi) and 0.5 <= lo < hi <= 5.5):
        raise ValueError(f"window_um must be (lo, hi) with 0.5 <= lo < hi <= 5.5, got {window_um}")
    return lo, hi


def stamp_half(grid: Grid) -> int:
    """Stamp half-size (native px) that covers the whole grid at any rotation, plus a margin."""
    return math.ceil(grid.fov_arcsec * math.sqrt(2) / 2 / config.PIXSCALE_ARCSEC) + 3


def reproject_planes(planes: Sequence[np.ndarray], wcs_in: WCS, grid: Grid,
                     min_good_weight: float) -> list[np.ndarray]:
    """`reproject_to_grid(plane, wcs_in, grid, min_good_weight)` for every plane, bit for
    bit, from one resampling call: the grid-to-frame mapping (with SIP, and reproject's
    round-trip check) is computed once for all planes instead of twice per plane."""
    from reproject import reproject_interp

    goods = [np.isfinite(p) for p in planes]
    cube = np.stack([np.where(g, p, 0.0) for g, p in zip(goods, planes)]
                    + [g.astype(np.float32) for g in goods])
    out, footprint = reproject_interp((cube, wcs_in), grid.wcs(), shape_out=grid.shape)
    resampled = np.where(footprint > 0, out, np.nan).astype(np.float32)
    n = len(planes)
    result = []
    for values, weight in zip(resampled[:n], resampled[n:]):
        usable = np.isfinite(weight) & (np.nan_to_num(weight) >= min_good_weight)
        with np.errstate(invalid="ignore", divide="ignore"):
            result.append(np.where(usable, values / weight, np.nan).astype(np.float32))
    return result


def frame_layer(s: Stamp, grid: Grid) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Zodi- and background-subtracted image and variance on the grid (NaN where bad).

    Also returns (flagged, usable) counts of native pixels whose centres fall on the grid,
    ignoring pixels that are off the detector.
    """
    good = good_mask(s)
    img = s.image - s.zodi
    bkg = clipped_median(img[good]) if good.sum() > 10 else 0.0
    w = s.wcs()
    # Normalised interpolation: plain bilinear made 6.5-7.7% of each real Eps Ind B frame
    # layer NaN from about 2% flagged pixels; normalised keeps it to 2.5%.
    data, var = reproject_planes([np.where(good, img - bkg, np.nan),
                                  np.where(good, s.variance, np.nan)], w, grid, MIN_GOOD_WEIGHT)
    yy, xx = np.mgrid[0:s.image.shape[0], 0:s.image.shape[1]]
    ra, dec = w.pixel_to_world_values(xx, yy)
    gx, gy = grid.sky_to_px(ra, dec)
    on = (gx >= 0) & (gx < grid.size_px) & (gy >= 0) & (gy < grid.size_px)
    on &= (s.flags & config.MISSING_MASK) == 0
    return data, var, int((on & ~good).sum()), int(on.sum())


def combine(images: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """Inverse-variance mean over axis 0, NaN-aware, with per-pixel outlier rejection.

    With 3+ values a value is dropped when it is more than REJECT_NSIG x max(robust scatter
    across frames, its own sigma) from the per-pixel median, so a cosmic ray or streak in
    one frame goes but a source whose flux changes across the window stays.
    """
    ok = np.isfinite(images) & np.isfinite(variances) & (variances > 0)
    if images.shape[0] >= MIN_FRAMES_TO_REJECT:
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels
            vals = np.where(ok, images, np.nan)
            med = np.nanmedian(vals, axis=0)
            mad = 1.4826 * np.nanmedian(np.abs(vals - med), axis=0)
            scale = np.maximum(mad, np.sqrt(np.where(ok, variances, np.nan)))
            ok &= ~(np.abs(vals - med) > REJECT_NSIG * scale)
    w = np.where(ok, 1.0 / np.where(ok, variances, 1.0), 0.0)
    ws = w.sum(axis=0)
    num = (w * np.where(ok, images, 0.0)).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ws > 0, num / ws, np.nan).astype(np.float32)


def _select(stamps: Sequence[Stamp], frames_mjd: Sequence[float], lo: float, hi: float,
            grid: Grid, target: Target | None) -> list[tuple[Stamp, str]]:
    """Stamps whose wavelength at the target (else the grid centre) is in [lo, hi).

    Each comes with its saturation reason at the target ("" when fine or no target).
    """
    out = []
    for s, mjd in zip(stamps, frames_mjd):
        ra, dec = position_at(target, mjd) if target else (grid.center_ra, grid.center_dec)
        x, y = s.pixel_of(ra, dec)
        wave, _ = s.wave_at_pixel(x, y)
        if lo <= wave < hi:
            out.append((s, core_reason(s, radius(s, x, y)) if target else ""))
    return out


def stack_pass(pas: Pass, grid: Grid, window_um: tuple[float, float], target: Target | None = None,
               store: BlockStore | None = None, workers: int = config.MAX_WORKERS) -> Stack | None:
    """Stack of the pass's frames in `window_um` on the fixed grid, or None if none cover it.

    Frames are chosen by the wavelength at the target's predicted position (or the grid
    centre without a target). Image in MJy/sr, zodi and background subtracted, display
    orientation, NaN where no frame has good data.
    """
    lo, hi = check_window(window_um)
    cands = [f for f in pas.frames if f.em_max_um >= lo and f.em_min_um <= hi]
    if not cands:
        return None
    jobs = [(f, grid.center_ra, grid.center_dec) for f in cands]
    batch = read_many(jobs, stamp_half(grid), with_psf=False, store=store, workers=workers)
    chosen = _select([s for _, s in batch.stamps], [f.mjd for f, _ in batch.stamps], lo, hi,
                     grid, target)
    if not chosen:
        return None
    layers = [frame_layer(s, grid) for s, _ in chosen]
    image = combine(np.array([la[0] for la in layers]), np.array([la[1] for la in layers]))
    flagged, usable = sum(la[2] for la in layers), sum(la[3] for la in layers)
    mjds = np.array([s.mjd for s, _ in chosen])
    notes = list(batch.warnings())
    n_sat = sum(reason == "saturated" for _, reason in chosen)
    if n_sat and n_sat >= SATURATED_SHARE * len(chosen):
        notes.insert(0, "saturated")
        log.info("target saturated in %d of %d frames", n_sat, len(chosen))
    return Stack(
        image=image, mission="SPHEREx", band=f"{lo:g}-{hi:g} um", wavelength_um=(lo, hi),
        mjd=float(mjds.mean()), date_span_days=float(np.ptp(mjds)), n_exposures=len(chosen),
        native_pixscale_arcsec=config.PIXSCALE_ARCSEC,
        flag_fraction=flagged / usable if usable else 0.0, warnings=tuple(notes))
