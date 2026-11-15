"""Per-frame spectrum of a (possibly moving) target over one pass.

Forced PSF photometry at the predicted position, corrected per pass by one common sky
offset when the pass has the signal to fit it (pxs.spherex.recentre).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

import numpy as np

from . import config
from .net import BlockStore
from .photometry import OFFSETS, error_scale, measure, measured_error_scale
from .read import Stamp
from .recentre import NONE, Recentre, Sky, fit_offset, sky_to_pixel_jacobian
from .stamps import position_at, read_many
from .types import Pass, SpecPoint, Target

log = logging.getLogger(__name__)


class Points(list):
    """The SpecPoints of one pass (a plain list to callers), plus `skipped`: the number of
    frames that could not be read after retries and so gave no point, and `recentre`: the
    pass's fitted position offset and whether it was applied."""

    def __init__(self, points: Iterable[SpecPoint] = (), skipped: int = 0,
                 recentre: Recentre = NONE) -> None:
        super().__init__(points)
        self.skipped = skipped
        self.recentre = recentre


MIN_DETECTOR_SAMPLES = 40  # empty-position measurements needed for a detector's own scale


def detector_scales(stamps: list[Stamp], overall: float | None = None) -> dict[int, float]:
    """Empirical error scale per detector, falling back to the pass-wide measured value
    (and to config.ERROR_SCALE only when the whole pass has too few samples).

    `overall`: the pass-wide error_scale when the caller has already measured it.
    """
    overall = error_scale(stamps) if overall is None else overall
    out = {}
    for det in sorted({s.detector for s in stamps}):
        own = measured_error_scale([s for s in stamps if s.detector == det],
                                   min_samples=MIN_DETECTOR_SAMPLES)
        out[det] = overall if own is None else own
    return out


# The 8 empty positions as fixed sky offsets (east, north arcsec): the OFFSETS pattern at
# the nominal pixel scale. Passes six months apart are rolled by about 180 degrees, so
# pixel-fixed offsets would land on different sky in each pass and hide the confusion
# noise that repeats at one sky position (WISE 0855 at 4.4-5.0 um, all passes: S/N 30 from
# the errors, 2 from pixel-fixed and 20 from sky-fixed empty positions).
SKY_OFFSETS: tuple[tuple[float, float], ...] = tuple(
    (dx * config.PIXSCALE_ARCSEC, dy * config.PIXSCALE_ARCSEC) for dx, dy in OFFSETS)


def _empty_fluxes(s: Stamp, jac: np.ndarray, sx: float, sy: float) -> tuple[float, ...]:
    """Forced fluxes (mJy, NaN where not measurable) at SKY_OFFSETS from the position."""
    out = []
    for east, north in SKY_OFFSETS:
        dx, dy = jac @ (east, north)
        e = measure(s, sx + float(dx), sy + float(dy))
        out.append(e.flux_mjy if e.ok else float("nan"))
    return tuple(out)


def to_points(stamps: list[Stamp], offset: tuple[float, float] = (0.0, 0.0),
              overall_scale: float | None = None) -> list[SpecPoint]:
    """One SpecPoint per stamp, errors scaled by the empty-position noise of its detector.

    `offset` (east, north arcsec) moves the forced position on the sky in every stamp;
    the 8 empty positions (SKY_OFFSETS, fixed on the sky) move with it.
    """
    if not stamps:
        return []
    scales = detector_scales(stamps, overall_scale)
    log.info("error scale per detector: %s",
             ", ".join(f"D{d} x{v:.2f}" for d, v in scales.items()))
    points = []
    for s in stamps:
        jac = sky_to_pixel_jacobian(s)
        sx, sy = (float(v) for v in jac @ offset)
        m = measure(s, sx, sy)
        empty = _empty_fluxes(s, jac, sx, sy)
        points.append(SpecPoint(
            wl_um=s.wave_um, bw_um=s.band_um, flux_mjy=m.flux_mjy,
            err_mjy=m.err_mjy * scales[s.detector], detector=s.detector, flagged=not m.ok,
            mjd=s.mjd, reason=m.reason, empty_mjy=empty))
    return sorted(points, key=lambda p: (p.mjd, p.detector))


def recentre_pass(stamps: Sequence[Stamp], neighbours: Sequence[Sky] | None = None,
                  target_sky: Sky | None = None, scale: float | None = None) -> Recentre:
    """The pass's common position offset (pxs.spherex.recentre), judged with its error
    scale (`scale`, measured here when not given)."""
    if not stamps:
        return NONE
    return fit_offset(stamps, error_scale(stamps) if scale is None else scale, neighbours,
                      target_sky)


def _mid_position(target: Target, pas: Pass) -> Sky:
    return position_at(target, 0.5 * (pas.mjd_start + pas.mjd_end))


def extract_spectrum(pas: Pass, target: Target, store: BlockStore | None = None,
                     workers: int = config.MAX_WORKERS,
                     neighbours: Sequence[Sky] | None = None) -> Points:
    """Forced PSF photometry in every frame of the pass, at the proper-motion position
    corrected by the pass's fitted common offset when that is applied.

    `neighbours`: catalogued sources that are not the target, (ra, dec) degrees at the
    pass epoch, or None when unknown (the recentring then uses its tighter safe limit).
    Returns one SpecPoint per frame that contains the target (the caller bins), sorted by
    MJD, as a `Points` list with the fitted offset in `Points.recentre`. Saturated or
    mostly masked frames give flagged points with NaN flux. Frames that fail to load after
    retries are skipped, logged and counted in `Points.skipped`.
    """
    jobs = [(f, *position_at(target, f.mjd)) for f in pas.frames]
    batch = read_many(jobs, config.STAMP_HALF, with_psf=True, store=store, workers=workers)
    name = target.name or "target"
    for w in batch.warnings():
        log.warning("%s: %s", name, w)
    stamps = [s for _, s in batch.stamps]
    overall = error_scale(stamps) if stamps else None
    rc = recentre_pass(stamps, neighbours, _mid_position(target, pas), overall)
    log.info("%s: offset (%+.2f, %+.2f) arcsec +- (%.2f, %.2f), %s", name, rc.east_arcsec,
             rc.north_arcsec, rc.err_east_arcsec, rc.err_north_arcsec,
             "applied" if rc.applied else f"not applied: {rc.reason}")
    offset = (rc.east_arcsec, rc.north_arcsec) if rc.applied else (0.0, 0.0)
    points = to_points(stamps, offset, overall)
    n_flag = sum(p.flagged for p in points)
    log.info("%s: %d points (%d flagged) from %d frames", name, len(points), n_flag,
             len(pas.frames))
    return Points(points, skipped=batch.n_failed, recentre=rc)
