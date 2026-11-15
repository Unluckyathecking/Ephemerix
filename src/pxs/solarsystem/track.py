"""SPHEREx exposures that contain a moving body, each with the body's position at its time.

1. A daily ephemeris over the survey span (seen from SPHEREx).
2. Keep the days when the solar elongation is inside ELONG_WINDOW_DEG: SPHEREx scans
   great circles roughly 90 deg from the Sun, so it can only see the body then.
3. Along those days, one SIA query (`pxs.spherex.find_frames`) every `step` days, with a
   radius that covers the body's motion over the step; keep frames whose time is within
   half a step of the query time. With the local frame index (PXS_SPHEREX_INDEX), days
   up to the index's last observation are instead tested in the index along the day's
   path (`index_frames`); later days use SIA cones when PXS_SPHEREX_INDEX_SIA_TAIL=1 and
   are otherwise left unsearched (Track.unsearched_after_mjd, warned in the manifest).
4. An exact ephemeris at each kept frame's mid-time (Horizons TLIST). Frames that do not
   actually contain the body drop out later, when `read_stamp` returns None.

Units: MJD (UTC), degrees, arcsec/hour.
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pxs.spherex import config as spx_config
from pxs.spherex import localindex
from pxs.spherex.localindex import FrameIndex
from pxs.spherex.query import find_frames, group_passes
from pxs.spherex.types import Frame, Pass

from .horizons import EphemPoint, ephemeris_at, ephemeris_range

log = logging.getLogger(__name__)

SURVEY_START_MJD = 60760.0  # 2025-03-26, before the first survey frame
# Frames found for Haumea with a 40-140 deg window had elongations 83.5-117.9 deg; this
# window keeps a margin on both sides (probes/solarsystem/elong_check.py).
ELONG_WINDOW_DEG = (78.0, 125.0)
MAX_STEP_DAYS = 5.0
RADIUS_MARGIN_DEG = 0.05
SIA_WORKERS = 2  # IRSA answered 502 to bursts of 8 parallel SIA queries
SIA_ATTEMPTS = 3
SIA_PAUSE_S = 5.0
# Local index path (PXS_SPHEREX_INDEX): the day's path is tested point by point, so the
# search circle only has to bridge the gap between points plus a small margin.
INDEX_SPACING_DEG = 0.02
INDEX_MARGIN_DEG = 0.01


@dataclass(frozen=True)
class Visit:
    """One exposure (one detector frame) with the body's ephemeris at its mid-time."""

    frame: Frame
    eph: EphemPoint


@dataclass(frozen=True)
class Query:
    """One SIA cone along the track: centre (deg), radius (deg), time window (MJD)."""

    ra: float
    dec: float
    radius_deg: float
    mjd_lo: float
    mjd_hi: float


def visible(eph: Sequence[EphemPoint],
            window: tuple[float, float] | None = None) -> list[EphemPoint]:
    """Ephemeris points at solar elongations SPHEREx can observe."""
    lo, hi = window or ELONG_WINDOW_DEG
    return [e for e in eph if lo <= e.elong_deg <= hi]


def plan_queries(eph: Sequence[EphemPoint]) -> list[Query]:
    """SIA cones that together cover the body's track at the given (daily) points.

    The step shrinks for fast movers so that half a step of motion stays under 0.5 deg.
    """
    out = []
    for e in eph:
        rate_deg_day = _rate_deg_day(e)
        step = min(MAX_STEP_DAYS, max(0.25, 1.0 / max(rate_deg_day, 1e-6)))
        n = max(1, round(1.0 / step))  # sub-steps inside this day for fast movers
        for k in range(n):
            t = e.mjd + (k + 0.5) / n - 0.5
            radius = min(1.0, rate_deg_day * (1.0 / n) / 2.0 + RADIUS_MARGIN_DEG)
            out.append(Query(*_at(e, t), radius, t - 0.5 / n, t + 0.5 / n))
    return out


def _rate_deg_day(e: EphemPoint) -> float:
    return e.rate_arcsec_h * 24.0 / 3600.0 if math.isfinite(e.rate_arcsec_h) else 1.0


def _at(e: EphemPoint, t: float) -> tuple[float, float]:
    """(ra, dec) at MJD t, moving linearly at the rates of point e."""
    dra = e.dra_cosd * (t - e.mjd) * 24 / 3600 / max(math.cos(math.radians(e.dec)), 1e-3)
    ddec = e.ddec * (t - e.mjd) * 24 / 3600
    return (e.ra + dra) % 360.0, e.dec + ddec


def day_path(e: EphemPoint) -> list[tuple[float, float]]:
    """Positions over the day centred on e, at most INDEX_SPACING_DEG of motion apart."""
    n = max(1, math.ceil(_rate_deg_day(e) / INDEX_SPACING_DEG))
    return [_at(e, e.mjd - 0.5 + k / n) for k in range(n + 1)]


def index_frames(idx: FrameIndex, eph: Sequence[EphemPoint]) -> list[Frame]:
    """Frames from the local index that cover the body's path on each day of `eph` and were
    taken on that day (FrameIndex.find over the day's path, exact TAN-SIP coverage)."""
    radius = INDEX_SPACING_DEG / 2 + INDEX_MARGIN_DEG
    uniq: dict[str, Frame] = {}
    for e in eph:
        lo, hi = e.mjd - 0.5, e.mjd + 0.5
        for f in idx.find(day_path(e), radius):
            if lo <= f.mjd < hi:
                uniq[f.s3_key] = f
    return sorted(uniq.values(), key=lambda f: (f.mjd, f.detector))


def merge_daily(queries: list[Query], max_days: float = MAX_STEP_DAYS) -> list[Query]:
    """Merge consecutive one-day cones of a slow body into cones of up to `max_days`."""
    out: list[Query] = []
    group: list[Query] = []

    def flush() -> None:
        if not group:
            return
        mid = group[len(group) // 2]
        reach = max(_sep(mid, q) for q in group) + max(q.radius_deg for q in group)
        out.append(Query(mid.ra, mid.dec, min(1.0, reach), group[0].mjd_lo, group[-1].mjd_hi))
        group.clear()

    for q in queries:
        contiguous = group and abs(q.mjd_lo - group[-1].mjd_hi) < 1e-6
        if contiguous and q.mjd_hi - group[0].mjd_lo <= max_days and _sep(group[0], q) < 0.4:
            group.append(q)
        else:
            flush()
            group.append(q)
    flush()
    return out


def _sep(a: Query, b: Query) -> float:
    dra = ((a.ra - b.ra + 180) % 360 - 180) * math.cos(math.radians(0.5 * (a.dec + b.dec)))
    return math.hypot(dra, a.dec - b.dec)


def _past(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def sia_frames(ra: float, dec: float, radius_deg: float = spx_config.POINT_RADIUS_DEG,
               deadline: float | None = None) -> list[Frame] | None:
    """All frames touching the circle, or None if a collection failed every try.

    Collections are queried one at a time so that one failing collection is retried
    instead of being silently skipped (find_frames skips a failed collection when another
    answers). Successful answers are cached by find_frames, so a retry is cheap. Past
    `deadline` (time.monotonic) no new query is started and None is returned, as if the
    archive had not answered.
    """
    out: list[Frame] = []
    for coll in spx_config.COLLECTIONS:
        for attempt in range(SIA_ATTEMPTS):
            if _past(deadline):
                return None
            try:
                out += find_frames(ra, dec, radius_deg, (coll,))
                break
            except RuntimeError as e:  # IRSA 5xx after retries; wait and try again
                log.info("SIA %s at %.4f %.4f failed (try %d): %s", coll, ra, dec,
                         attempt + 1, e)
                time.sleep(SIA_PAUSE_S * (attempt + 1))
        else:
            log.warning("SIA %s at %.4f %.4f failed %d times", coll, ra, dec, SIA_ATTEMPTS)
            return None
    return out


def _cone(q: Query, deadline: float | None = None) -> list[Frame] | None:
    """Frames of one cone inside its time window; None if the archive did not answer."""
    frames = sia_frames(q.ra, q.dec, q.radius_deg, deadline)
    return None if frames is None else [f for f in frames if q.mjd_lo <= f.mjd < q.mjd_hi]


def frames_for(queries: Sequence[Query],
               deadline: float | None = None) -> tuple[list[Frame], int]:
    """Frames from every cone whose time lies inside that cone's window (deduplicated),
    and the number of cones the archive could not answer (or that `deadline` cut off)."""
    with ThreadPoolExecutor(max_workers=SIA_WORKERS) as ex:
        results = list(ex.map(lambda q: _cone(q, deadline), queries))
    found = [f for fs in results if fs for f in fs]
    uniq = {f.s3_key: f for f in found}
    failed = sum(r is None for r in results)
    return sorted(uniq.values(), key=lambda f: (f.mjd, f.detector)), failed


@dataclass(frozen=True)
class Track:
    """Candidate visits along the body's track, and how much of the track was searched."""

    visits: tuple[Visit, ...]
    daily: tuple[EphemPoint, ...]
    n_cones: int  # SIA cones asked
    failed_cones: int
    n_index_days: int = 0  # days searched in the local frame index
    unsearched_after_mjd: float | None = None  # index end, when later days were skipped


def usable_index() -> FrameIndex | None:
    """The local frame index when it holds every survey release searched, else None."""
    idx = localindex.current()
    wanted = {c.removeprefix("spherex_") for c in spx_config.COLLECTIONS}
    return idx if idx is not None and wanted <= idx.releases else None


def _sia_tail() -> bool:
    """PXS_SPHEREX_INDEX_SIA_TAIL is on: find_frames also asks SIA past the index end."""
    return os.environ.get(localindex.ENV_TAIL, "").strip().lower() in ("1", "true", "yes", "on")


def find_visits(command: str, mjd_stop: float, mjd_start: float = SURVEY_START_MJD,
                sia_deadline: float | None = None) -> Track:
    """Every frame that may contain the body, with the exact ephemeris at its mid-time.

    With a local frame index, days up to its last observation are searched there; later
    days (and every day without an index) go to SIA. SIA cones not answered by
    `sia_deadline` (time.monotonic) count as failed cones.
    """
    daily = ephemeris_range(command, mjd_start, mjd_stop, "1d")
    vis = visible(daily)
    log.info("%s: %d of %d days at observable elongation", command, len(vis), len(daily))
    idx = usable_index()
    indexed: list[Frame] = []
    in_idx: list[EphemPoint] = []
    unsearched = None
    if idx is not None:
        end = idx.max_mjd(sorted(c.removeprefix("spherex_") for c in spx_config.COLLECTIONS))
        in_idx = [e for e in vis if e.mjd + 0.5 <= end]
        vis = [e for e in vis if e.mjd + 0.5 > end]
        indexed = index_frames(idx, in_idx)
        log.info("%s: %d days from the local index, %d candidate frames", command,
                 len(in_idx), len(indexed))
        if vis and not _sia_tail():  # find_frames would answer these from the index alone
            log.warning("%s: %d visible days after the index end (MJD %.2f) not searched",
                        command, len(vis), end)
            unsearched, vis = end, []
    queries = merge_daily(plan_queries(vis))
    sia, failed = frames_for(queries, sia_deadline) if queries else ([], 0)
    log.info("%s: %d SIA cones (%d failed), %d candidate frames", command, len(queries),
             failed, len(sia))
    frames = sorted({f.s3_key: f for f in indexed + sia}.values(),
                    key=lambda f: (f.mjd, f.detector))
    eph = ephemeris_at(command, [f.mjd for f in frames]) if frames else []
    return Track(tuple(Visit(f, e) for f, e in zip(frames, eph)), tuple(daily), len(queries),
                 failed, len(in_idx), unsearched)


def passes_of(visits: Sequence[Visit],
              gap_days: float = spx_config.PASS_GAP_DAYS) -> list[tuple[Pass, list[Visit]]]:
    """Visits grouped into survey passes (gap > gap_days), in time order."""
    by_key = {v.frame.s3_key: v for v in visits}
    return [(p, [by_key[f.s3_key] for f in p.frames])
            for p in group_passes([v.frame for v in visits], gap_days)]
