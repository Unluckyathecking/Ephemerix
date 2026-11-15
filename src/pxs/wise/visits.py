"""Group single exposures into visits and attach the target position at each visit.

WISE sees a given position for a day or two every six months. Frames separated by more than
``VISIT_GAP_DAYS`` start a new visit. Near the ecliptic poles coverage is continuous, so a run
longer than ``LONG_VISIT_DAYS`` is split into half-year bins.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from astropy.coordinates import angular_separation

from pxs.astrometry import decimal_year, propagate
from pxs.wise.frames import Frame
from pxs.wise.geometry import edge_distance_arcsec
from pxs.wise.search import IRSA_WORKERS, search_frames

log = logging.getLogger(__name__)

VISIT_GAP_DAYS = 20.0
LONG_VISIT_DAYS = 60.0
TARGET_MARGIN_ARCSEC = 22.0  # 8 native pixels: the target's PSF must be on the frame
DEFAULT_RADIUS_DEG = 0.002
MAX_RADIUS_DEG = 2.0

Track = Sequence[tuple[float, float, float]]  # (mjd, ra_deg, dec_deg) samples, increasing mjd


class Visits(list):
    """The visits found (a plain list to callers), plus ``warnings`` (sentences for the user)
    and ``partial`` (some frames could not be listed); see ``search.search_frames``."""

    def __init__(self, visits: Iterable[Visit] = (), warnings: tuple[str, ...] = (),
                 partial: bool = False) -> None:
        super().__init__(visits)
        self.warnings, self.partial = warnings, partial


@dataclass(frozen=True)
class Visit:
    """Frames (both bands) from one visit that cover the target at that visit.

    ``target_ra``/``target_dec`` (deg) is the target position at the visit's mean MJD.
    """

    frames: tuple[Frame, ...]
    target_ra: float
    target_dec: float

    @property
    def mjd_start(self) -> float:
        return min(f.mjd for f in self.frames)

    @property
    def mjd_end(self) -> float:
        return max(f.mjd for f in self.frames)

    @property
    def mjd_mean(self) -> float:
        return float(np.mean([f.mjd for f in self.frames]))

    @property
    def bands(self) -> tuple[str, ...]:
        return tuple(sorted({f.band for f in self.frames}))

    def frames_in(self, band: str) -> tuple[Frame, ...]:
        return tuple(f for f in self.frames if f.band == band)


def group_visits(frames: Sequence[Frame]) -> list[tuple[Frame, ...]]:
    """Split frames into visits on time gaps; long continuous runs go into half-year bins."""
    ordered = sorted(frames, key=lambda f: f.mjd)
    runs: list[list[Frame]] = []
    for f in ordered:
        if runs and f.mjd - runs[-1][-1].mjd <= VISIT_GAP_DAYS:
            runs[-1].append(f)
        else:
            runs.append([f])
    out: list[tuple[Frame, ...]] = []
    for run in runs:
        if run[-1].mjd - run[0].mjd <= LONG_VISIT_DAYS:
            out.append(tuple(run))
            continue
        bins: dict[int, list[Frame]] = {}
        for f in run:
            bins.setdefault(math.floor(float(decimal_year(f.mjd)) * 2), []).append(f)
        out.extend(tuple(bins[k]) for k in sorted(bins))
    return out


def path_from_motion(ra: float, dec: float, epoch: float, pmra_masyr: float,
                     pmdec_masyr: float, start_year: float = 2009.9,
                     end_year: float = 2025.0, step_years: float = 0.1) -> list[tuple[float, float, float]]:
    """A (mjd, ra, dec) path from linear proper motion (mas/yr, pmra includes cos dec)."""
    years = np.arange(start_year, end_year + step_years / 2, step_years)
    ras, decs = propagate(ra, dec, epoch, pmra_masyr, pmdec_masyr, years)
    mjds = 51544.5 + (years - 2000.0) * 365.25
    return list(zip(mjds.tolist(), np.atleast_1d(ras).tolist(), np.atleast_1d(decs).tolist()))


def _position(path: Track | None, ra: float, dec: float, mjd: float) -> tuple[float, float] | None:
    """Target position at ``mjd``: interpolated on the path, or the fixed (ra, dec)."""
    if path is None:
        return ra, dec
    t = np.array([p[0] for p in path])
    if not t[0] <= mjd <= t[-1]:
        return None
    ras = np.degrees(np.unwrap(np.radians([p[1] for p in path])))
    return float(np.interp(mjd, t, ras) % 360.0), float(np.interp(mjd, t, [p[2] for p in path]))


def _validate(ra: float, dec: float, radius_deg: float, path: Track | None) -> None:
    if not (math.isfinite(ra) and 0.0 <= ra < 360.0):
        raise ValueError(f"ra must be in [0, 360) deg, got {ra}")
    if not (math.isfinite(dec) and -90.0 <= dec <= 90.0):
        raise ValueError(f"dec must be in [-90, 90] deg, got {dec}")
    if not 0.0 < radius_deg <= MAX_RADIUS_DEG:
        raise ValueError(f"radius_deg must be in (0, {MAX_RADIUS_DEG}], got {radius_deg}")
    if path is not None and (len(path) < 2 or any(b[0] <= a[0] for a, b in pairwise(path))):
        raise ValueError("path needs at least 2 (mjd, ra, dec) points with increasing mjd")


def _search_radius(ra: float, dec: float, radius_deg: float, path: Track | None) -> float:
    if path is None:
        return radius_deg
    seps = angular_separation(*np.radians([ra, dec]),
                              np.radians([p[1] for p in path]), np.radians([p[2] for p in path]))
    return radius_deg + float(np.degrees(np.max(seps)))


def find_visits(ra: float, dec: float, radius_deg: float = DEFAULT_RADIUS_DEG, *,
                path: Track | None = None, irsa_workers: int = IRSA_WORKERS) -> Visits:
    """Visits with W1/W2 frames covering the target, oldest first. Angles in degrees.

    Without ``path`` the target sits at (ra, dec). With ``path`` (mjd, ra, dec samples
    spanning 2010-2024, e.g. from ``path_from_motion``) the search covers the whole path and
    each frame is kept only if it covers the target where the path puts it at that frame's
    time. Frames with ``qual_frame`` 0 are dropped. ``Visits.warnings`` carries the search's
    sentences for the user and ``Visits.partial`` whether frames are missing.
    """
    _validate(ra, dec, radius_deg, path)
    frames = search_frames(ra, dec, _search_radius(ra, dec, radius_deg, path), irsa_workers)
    kept, dropped = [], {"qual0": 0, "off_frame": 0, "off_path": 0}
    for f in frames:
        pos = _position(path, ra, dec, f.mjd)
        if pos is None:
            dropped["off_path"] += 1
        elif f.qual_frame == 0:
            dropped["qual0"] += 1
        elif edge_distance_arcsec(f.corners, *pos) < TARGET_MARGIN_ARCSEC:
            dropped["off_frame"] += 1
        else:
            kept.append(f)
    log.info("find_visits: kept %d of %d frames, dropped %s", len(kept), len(frames), dropped)
    visits = []
    for group in group_visits(kept):
        mean_mjd = float(np.mean([f.mjd for f in group]))
        pos = _position(path, ra, dec, mean_mjd)
        if pos is not None:
            visits.append(Visit(frames=group, target_ra=pos[0], target_dec=pos[1]))
    return Visits(visits, tuple(getattr(frames, "warnings", ())),
                  partial=bool(getattr(frames, "partial", False)))
