"""Stack one visit in one band onto the common grid: read, subtract background, resample,
combine. The result is fixed on the sky, in display orientation, in DN.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from pxs.grid import Grid, Stack, reproject_to_grid
from pxs.wise.combine import combine
from pxs.wise.frames import Frame
from pxs.wise.phases import BANDS
from pxs.wise.reader import Exposure, read_exposure
from pxs.wise.select import DEFAULT_MAX_FRAMES, choose_frames
from pxs.wise.visits import TARGET_MARGIN_ARCSEC, Visit

log = logging.getLogger(__name__)

WAVELENGTH_UM = {"W1": (3.0, 3.8), "W2": (4.0, 5.2)}
NATIVE_PIXSCALE_ARCSEC = 2.75
S3_WORKERS = 16
SATURATION_RADIUS_ARCSEC = 8.0
MIN_SATURATED_PIXELS = 3
MIN_GOOD_WEIGHT = 0.5

Reader = Callable[[Frame, Grid], Exposure | None]


def _read_all(frames: list[Frame], grid: Grid, read: Reader,
              workers: int) -> tuple[list[Exposure], int]:
    """Read frames concurrently; returns the exposures that cover the grid and the failures."""

    def one(f: Frame) -> Exposure | None | Exception:
        try:
            return read(f, grid)
        except (requests.RequestException, OSError, ValueError) as exc:  # after retries
            log.warning("skipping %s: %s: %s", f.key, type(exc).__name__, exc)
            return exc

    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(one, frames))
    failed = sum(isinstance(r, Exception) for r in results)
    return [r for r in results if isinstance(r, Exposure)], failed


def _covers_target(exp: Exposure, ra: float, dec: float) -> bool:
    """Exact test with the frame WCS: the target lies at least the margin inside the frame."""
    x, y = exp.wcs.all_world2pix(ra, dec, 0)
    margin = TARGET_MARGIN_ARCSEC / NATIVE_PIXSCALE_ARCSEC
    ny, nx = exp.full_shape
    y_full = float(y) + exp.y0
    return margin <= float(x) <= nx - 1 - margin and margin <= y_full <= ny - 1 - margin


def _layer(exp: Exposure, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Background-subtracted image on the grid and its coverage mask.

    Flagged (NaN) input pixels are handled by normalised interpolation: the data with flags
    set to 0 and the good-pixel mask are resampled alike and divided. A grid pixel is NaN only
    when good pixels carry less than MIN_GOOD_WEIGHT of its interpolation weight. Plain
    bilinear resampling would spread every flagged pixel to its neighbours (late NEOWISE
    frames have about 6% flagged pixels, which became about 30% of the grid).
    """
    good = np.isfinite(exp.data)
    background = float(np.median(exp.data[good])) if good.any() else 0.0
    # One resampling call for both planes: the grid-to-frame mapping (with SIP) is the
    # costly part and is the same for both (same output, bit for bit, as two calls).
    values, weight = reproject_to_grid(
        np.stack([np.where(good, exp.data - background, 0.0), good.astype(np.float32)]),
        exp.wcs, grid)
    covered = np.isfinite(weight)
    usable = covered & (np.nan_to_num(weight) >= MIN_GOOD_WEIGHT)
    with np.errstate(invalid="ignore", divide="ignore"):
        image = np.where(usable, values / weight, np.nan).astype(np.float32)
    return image, covered


def _validate(visit: Visit, band: str, grid: Grid, max_frames: int, workers: int) -> None:
    if not isinstance(visit, Visit):
        raise TypeError("visit must be a pxs.wise.Visit")
    if band not in BANDS:
        raise ValueError(f"band must be one of {BANDS}, got {band!r}")
    if not isinstance(grid, Grid) or grid.size_px < 1 or not grid.fov_arcsec > 0:
        raise ValueError("grid must be a pxs.grid.Grid with positive size and field of view")
    if max_frames < 1 or workers < 1:
        raise ValueError("max_frames and workers must be at least 1")


def _target_saturated(saturated: np.ndarray, grid: Grid, ra: float, dec: float) -> bool:
    x, y = grid.sky_to_px(ra, dec)
    yy, xx = np.mgrid[0:grid.size_px, 0:grid.size_px] + 0.5  # pixel centres, edge convention
    near = np.hypot(xx - float(x), yy - float(y)) * grid.pixscale_arcsec
    return int((saturated & (near <= SATURATION_RADIUS_ARCSEC)).sum()) >= MIN_SATURATED_PIXELS


def _warnings(n_failed: int, n_unknown: int, saturated: bool, partial: bool) -> tuple[str, ...]:
    out = []
    if saturated:
        out.append("saturated")
    if partial:
        out.append("partial coverage")
    if n_failed:
        out.append(f"{n_failed} frames failed to download")
    if n_unknown:
        out.append(f"frame quality unknown for {n_unknown} frames")
    return tuple(out)


def stack_visit(visit: Visit, band: str, grid: Grid, *, max_frames: int = DEFAULT_MAX_FRAMES,
                workers: int = S3_WORKERS, read: Reader | None = None) -> Stack | None:
    """Stack the best ``max_frames`` frames of a visit in ``band`` ("W1"/"W2") onto ``grid``.

    Returns None when no good frame covers the grid. Pixel values are background-subtracted
    DN (mean over the frames that survive outlier rejection), NaN where no frame covers.
    """
    _validate(visit, band, grid, max_frames, workers)
    ra, dec = visit.target_ra, visit.target_dec
    chosen = choose_frames(visit.frames_in(band), grid, ra, dec, max_frames)
    if not chosen:
        return None
    exposures, n_failed = _read_all(chosen, grid, read or read_exposure, workers)
    exposures = [e for e in exposures if _covers_target(e, ra, dec)]
    layers = [_layer(e, grid) for e in exposures]
    result = combine([im for im, _ in layers], [cov for _, cov in layers]) if layers else None
    if result is None:
        log.info("visit %.1f %s: no usable frame (%d failed)", visit.mjd_mean, band, n_failed)
        return None
    used = [exposures[i].frame for i in result.kept]
    mjds = [f.mjd for f in used]
    flags = _warnings(n_failed, sum(f.qual_frame is None for f in used),
                      _target_saturated(result.saturated, grid, ra, dec),
                      not bool(result.covered.all()))
    return Stack(image=result.image, mission="WISE", band=band,
                 wavelength_um=WAVELENGTH_UM[band], mjd=float(np.mean(mjds)),
                 date_span_days=float(max(mjds) - min(mjds)), n_exposures=len(used),
                 native_pixscale_arcsec=NATIVE_PIXSCALE_ARCSEC,
                 flag_fraction=round(result.flag_fraction, 4),
                 warnings=flags, unit="DN", saturated_mask=result.saturated)
