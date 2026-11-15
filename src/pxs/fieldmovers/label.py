"""Say what a moving track is: the target, a known Gaia star, a known CatWISE source, or
none of them.

A catalogue explains a mover only when its motion matches in size and direction: the
difference of the two motion vectors must be within AGREE_SIGMA of the measured error or
AGREE_FRACTION of the measured motion, whichever is larger. A catalogued source at the same
place is not enough.

- target: the track passes within MATCH_ARCSEC (plus 3 sigma of the track) of the target, at
  the track's mean epoch when the target's motion is known and at the target's own epoch when
  it is not.
- gaia: a Gaia DR3 star with a proper motion lies within MATCH_ARCSEC of the track at its
  mean epoch and the motions agree. When they do not agree the track is CONTRADICTED: Gaia
  measures that star far better than WISE can, so the track is a false alarm of this search
  (a blend, usually), and it is counted but not listed.
- catwise: a CatWISE2020 source lies within MATCH_ARCSEC of the track's 2010-2019 path (as
  `blend.is_catwise_piece`: CatWISE cuts a fast mover into pieces) and its motion agrees.
  CatWISE is made from the same WISE images to 2018, so this says the motion is already
  catalogued, not that it is independently confirmed.
- candidate: everything else. Written with Claude Code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from pxs.astrometry import propagate, sky_to_px
from pxs.blend import CATWISE_YEARS
from pxs.fieldmovers.link import Track
from pxs.grid import Grid
from pxs.target import Target

MATCH_ARCSEC = 3.0
AGREE_SIGMA = 3.0
AGREE_FRACTION = 0.3
TARGET, GAIA, CATWISE, CANDIDATE, CONTRADICTED = (
    "target", "gaia", "catwise", "candidate", "contradicted")


def motion_masyr(tr: Track, pixscale: float) -> tuple[float, float, float]:
    """(pmra, pmdec, 1-sigma error per axis) in mas/yr; x grows west and y south."""
    k = pixscale * 1000.0
    return -tr.vx * k, -tr.vy * k, tr.err_v * k


def agrees(pm: tuple[float, float], err: float, other: tuple[float, float]) -> bool:
    """True when motion `other` matches the measured `pm` (+- `err` per axis), all mas/yr."""
    diff = math.hypot(pm[0] - other[0], pm[1] - other[1])
    return diff <= max(AGREE_SIGMA * err, AGREE_FRACTION * math.hypot(*pm))


def _px(sources: Sequence[dict], grid: Grid, year: float | None) -> np.ndarray:
    """(n, 2) pixel positions of catalogue sources at `year` (their own epoch if None)."""
    if not sources:
        return np.zeros((0, 2))
    ra, dec = (np.array([s[k] for s in sources], float) for k in ("ra", "dec"))
    if year is not None:
        pm = [np.array([s.get(k) or 0.0 for s in sources], float)
              for k in ("pmra_masyr", "pmdec_masyr")]
        epoch = np.array([s["epoch"] for s in sources], float)
        ra, dec = propagate(ra, dec, epoch, pm[0], pm[1], year)
    x, y = sky_to_px(ra, dec, grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
    return np.column_stack([x, y])


def _has_pm(s: dict) -> bool:
    return s.get("pmra_masyr") is not None and s.get("pmdec_masyr") is not None


def is_target(tr: Track, target: Target, grid: Grid) -> bool:
    year = tr.t0 if target.has_pm else target.epoch
    ra, dec = target.ra, target.dec
    if target.has_pm:
        ra, dec = propagate(ra, dec, target.epoch, target.pmra_masyr, target.pmdec_masyr, year)
    x, y = sky_to_px(ra, dec, grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
    tx, ty = tr.at(year)
    sigma = math.hypot(tr.err_xy0, tr.err_v * (year - tr.t0))
    return math.hypot(float(x) - tx, float(y) - ty) <= MATCH_ARCSEC / grid.pixscale_arcsec \
        + 3.0 * sigma


def _gaia(tr: Track, gaia: Sequence[dict], grid: Grid) -> tuple[str, str] | None:
    """(GAIA or CONTRADICTED, source id) for a Gaia star with a motion at the track's place."""
    xy = _px(gaia, grid, tr.t0)
    d = np.hypot(xy[:, 0] - tr.x0, xy[:, 1] - tr.y0) * grid.pixscale_arcsec
    near = [gaia[i] for i in np.argsort(d) if d[i] <= MATCH_ARCSEC and _has_pm(gaia[i])]
    pmra, pmdec, err = motion_masyr(tr, grid.pixscale_arcsec)
    for s in near:
        if agrees((pmra, pmdec), err, (s["pmra_masyr"], s["pmdec_masyr"])):
            return GAIA, str(s["id"])
    return (CONTRADICTED, str(near[0]["id"])) if near else None


def _path_distance(xy: np.ndarray, a: tuple[float, float], b: tuple[float, float]) -> np.ndarray:
    """Distance (px) of each point of `xy` from the segment a-b."""
    a_, ab = np.array(a), np.array(b) - np.array(a)
    f = np.clip(((xy - a_) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return np.hypot(*(xy - a_ - f[:, None] * ab).T)


def _catwise(tr: Track, catwise: Sequence[dict], grid: Grid) -> tuple[str | None, str | None]:
    """(id of a CatWISE source on the path whose motion agrees, id of the nearest on the
    path whatever its motion); None where there is none."""
    xy = _px(catwise, grid, None)
    d = _path_distance(xy, tr.at(CATWISE_YEARS[0]), tr.at(CATWISE_YEARS[1])) \
        * grid.pixscale_arcsec
    on = [catwise[i] for i in np.argsort(d) if d[i] <= MATCH_ARCSEC]
    pmra, pmdec, err = motion_masyr(tr, grid.pixscale_arcsec)
    ok = [s for s in on if _has_pm(s)
          and agrees((pmra, pmdec), err, (s["pmra_masyr"], s["pmdec_masyr"]))]
    return (str(ok[0]["id"]) if ok else None), (str(on[0]["id"]) if on else None)


def label(tr: Track, target: Target, grid: Grid, gaia: Sequence[dict],
          catwise: Sequence[dict]) -> dict:
    """{"label", "gaia_id", "catwise_id"} of a moving track."""
    agreeing, nearest = _catwise(tr, catwise, grid)
    out = {"label": CANDIDATE, "gaia_id": None, "catwise_id": agreeing or nearest}
    if is_target(tr, target, grid):
        return {**out, "label": TARGET}
    hit = _gaia(tr, gaia, grid)
    if hit is not None:
        return {**out, "label": hit[0], "gaia_id": hit[1]}
    return {**out, "label": CATWISE} if agreeing else out
