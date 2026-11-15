"""Forced ePSF photometry at the ephemeris position in every exposure of a pass.

Reuses `pxs.spherex.stamps.read_many` (stamp cache, retries) and
`pxs.spherex.spectrum.to_points` (photometry plus the per-detector empty-position error
scale) unchanged. Each frame is read once, at the stamp size the stacks need, with its
PSF, and that stamp serves both the photometry and the image stacks.

Units: mJy (F_nu), micrometres, MJD.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from pxs import procs
from pxs.concurrency import map_ordered
from pxs.spherex import config as spx_config
from pxs.spherex.net import BlockStore
from pxs.spherex.read import Stamp
from pxs.spherex.spectrum import to_points
from pxs.spherex.stamps import read_many
from pxs.spherex.types import Frame, SpecPoint

from .track import Visit

log = logging.getLogger(__name__)

# Detector bands, as pxs.sources.SPHEREX_WINDOWS (copied: sources.py is being edited
# elsewhere and must not be imported for a constant; tests check they agree).
BANDS: dict[str, tuple[float, float]] = {
    "spx-b1": (0.75, 1.10), "spx-b2": (1.10, 1.65), "spx-b3": (1.65, 2.42),
    "spx-b4": (2.42, 3.82), "spx-b5": (3.82, 4.42), "spx-b6": (4.42, 5.00),
}


OUTLIER_BIT = 1 << spx_config.FLAG_BITS["OUTLIER"]
OUTLIER_RADIUS_PX = spx_config.R_FIT + 1.0  # covers the fit aperture plus ephemeris error
CLIP_SIGMA = 5.0
CHUNK_FRAMES = 8  # frames per worker-process call when PXS_PROCESSES is on


@dataclass(frozen=True)
class Measured:
    """One read frame: its visit, its stamp and its photometry point."""

    visit: Visit
    stamp: Stamp
    point: SpecPoint


@dataclass(frozen=True)
class BandFlux:
    """Inverse-variance mean flux of the usable points in one wavelength range (mJy)."""

    band: str
    n: int
    flux_mjy: float
    err_mjy: float

    @property
    def snr(self) -> float:
        return self.flux_mjy / self.err_mjy if self.err_mjy > 0 else math.nan

    def to_dict(self) -> dict:
        lo, hi = BANDS.get(self.band, (math.nan, math.nan))
        r = lambda v: None if not math.isfinite(v) else round(v * 1000.0, 2)
        return {"band": self.band, "wavelength_um": [lo, hi], "n": self.n,
                "flux_ujy": r(self.flux_mjy), "err_ujy": r(self.err_mjy),
                "snr": None if not math.isfinite(self.snr) else round(self.snr, 2)}


ReadJob = tuple[Frame, float, float]


def read_chunk(jobs: list[ReadJob], half: int) -> tuple[list[tuple[Frame, Stamp]], int]:
    """read_many over a few frames: (frame, stamp) pairs read and the failure count. Runs in
    an "io" worker process when PXS_PROCESSES is on (header parsing is CPU-bound)."""
    batch = read_many(jobs, half, with_psf=True)
    return list(batch.stamps), batch.n_failed


_read_chunk_io = procs.offloaded(read_chunk, pool="io")


def _read_all(jobs: list[ReadJob], half: int,
              store: BlockStore | None) -> tuple[list[tuple[Frame, Stamp]], int]:
    """Every stamp, on worker processes in chunks when they are on, else on threads here."""
    if not (procs.workers() and store is None):
        batch = read_many(jobs, half, with_psf=True, store=store)
        return list(batch.stamps), batch.n_failed
    chunks = [jobs[i:i + CHUNK_FRAMES] for i in range(0, len(jobs), CHUNK_FRAMES)]
    workers = max(1, spx_config.PASS_WORKERS // CHUNK_FRAMES * 2)
    results = map_ordered(lambda c: _read_chunk_io(c, half), chunks, workers,
                          name="pxs-body-read")
    return [p for pairs, _ in results for p in pairs], sum(n for _, n in results)


def read_visits(visits: Sequence[Visit], half: int = spx_config.STAMP_HALF,
                store: BlockStore | None = None) -> tuple[list[tuple[Visit, Stamp]], int]:
    """Stamps at the ephemeris position, each with its visit, and the number of read failures.

    Frames that do not contain the position (None from read_stamp) are dropped.
    """
    jobs = [(v.frame, v.eph.ra, v.eph.dec) for v in visits]
    stamps, failed = _read_all(jobs, half, store)
    by_key = {v.frame.s3_key: v for v in visits}
    return [(by_key[f.s3_key], s) for f, s in stamps], failed


def unflag_outlier(s: Stamp, r_px: float = OUTLIER_RADIUS_PX) -> Stamp:
    """A copy of the stamp with the OUTLIER bit cleared within r_px of its target position.

    The SPHEREx Level-2 pipeline sets OUTLIER on pixels that disagree with the static sky,
    which is exactly where a moving body is: on Haumea it masked the body's core in 33-42
    of about 110 exposures per pass, almost all in detectors 1-3 where the body is bright,
    so the brightest measurements were the ones thrown away. Every other bit (cosmic rays,
    saturation, bad pixels) still masks, and OUTLIER still masks away from the target.
    The input stamp is not changed.
    """
    yy, xx = np.mgrid[0:s.flags.shape[0], 0:s.flags.shape[1]]
    near = np.hypot(xx + s.x0 - s.xpix, yy + s.y0 - s.ypix) <= r_px
    flags = np.where(near, s.flags & ~np.int32(OUTLIER_BIT), s.flags).astype(np.int32)
    flags.setflags(write=False)
    return replace(s, flags=flags)


def measure_pass(read: Sequence[tuple[Visit, Stamp]]) -> list[Measured]:
    """Photometry of one pass's stamps, errors scaled per detector by empty positions.

    OUTLIER is cleared at the target position first (see `unflag_outlier`); the returned
    stamps are those copies, so the stacks see the body too.
    """
    if not read:
        return []
    read = [(v, unflag_outlier(s)) for v, s in read]
    stamps = [s for _, s in read]
    points = to_points(stamps)  # sorted by (mjd, detector); match back by both
    by = {(round(p.mjd, 7), p.detector, round(p.wl_um, 6)): p for p in points}
    out = []
    for v, s in read:
        p = by.get((round(s.mjd, 7), s.detector, round(s.wave_um, 6)))
        if p is not None:
            out.append(Measured(v, s, p))
    return out


def usable(p: SpecPoint) -> bool:
    return (not p.flagged and math.isfinite(p.flux_mjy) and math.isfinite(p.err_mjy)
            and p.err_mjy > 0)


def clip(points: list[SpecPoint], nsig: float = CLIP_SIGMA) -> list[SpecPoint]:
    """Drop points more than nsig x max(robust scatter, own error) from the median.

    A frame where a star or artefact falls on the position (body or control) is removed;
    the body's real colour changes across a detector band stay inside the scatter. Needs
    at least 4 points, else returns them all. On Haumea, without this one control frame set
    gave -166 +- 12 uJy at 3.8-4.4 um and a false 7-sigma "detection" of the body there.
    """
    if len(points) < 4:
        return points
    f = np.array([p.flux_mjy for p in points])
    med = float(np.median(f))
    mad = 1.4826 * float(np.median(np.abs(f - med)))
    return [p for p in points if abs(p.flux_mjy - med) <= nsig * max(mad, p.err_mjy)]


def band_flux(points: Sequence[SpecPoint], band: str,
              window: tuple[float, float] | None = None) -> BandFlux:
    """Inverse-variance mean over the usable points with lo <= wl < hi."""
    lo, hi = window or BANDS[band]
    use = clip([p for p in points if usable(p) and lo <= p.wl_um < hi])
    if not use:
        return BandFlux(band, 0, math.nan, math.nan)
    w = np.array([1 / p.err_mjy**2 for p in use])
    f = np.array([p.flux_mjy for p in use])
    return BandFlux(band, len(use), float(np.sum(w * f) / np.sum(w)), float(1 / np.sqrt(w.sum())))


def all_bands(points: Sequence[SpecPoint]) -> list[BandFlux]:
    return [band_flux(points, b) for b in BANDS]


def subtract(body: BandFlux, control: BandFlux) -> BandFlux:
    """Body minus control, errors in quadrature (NaN if either is missing)."""
    if body.n == 0 or control.n == 0:
        return BandFlux(body.band, body.n, math.nan, math.nan)
    return BandFlux(body.band, body.n, body.flux_mjy - control.flux_mjy,
                    math.hypot(body.err_mjy, control.err_mjy))
