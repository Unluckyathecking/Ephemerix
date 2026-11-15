"""The search on one field's layers: difference, matched filter, stack, detect, and the null.

`run_core` is shared by the product search, the injection-recovery runs and the null
searches, so completeness and false-alarm rates are measured with exactly the pipeline
that produces the candidates.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .candidates import Detection, detect
from .difference import Cube, difference_cube
from .geometry import PassGeometry, TrajectoryGrid, pass_geometry, trajectory_grid
from .layers import Layer
from .matched import Planes, planes, reflected_template
from .search import SearchMaps, Trials, make_trials, run_search, track_sums

log = logging.getLogger(__name__)

THRESHOLD = 7.0  # clipped S/N for a candidate (study A7: < 1 noise peak per field)
SEED_THRESHOLD = 5.0  # raw-map peaks examined (kept for diagnostics and vetting)


@dataclass(frozen=True)
class CoreResult:
    """Detections down to SEED_THRESHOLD for the real and the mirrored (null) search."""

    cube: Cube
    planes: Planes
    geom: PassGeometry
    tgrid: TrajectoryGrid
    trials: Trials
    maps: SearchMaps
    detections: tuple[Detection, ...]
    null_detections: tuple[Detection, ...]

    def above(self, threshold: float = THRESHOLD, null: bool = False) -> list[Detection]:
        src = self.null_detections if null else self.detections
        return [d for d in src if d.snr >= threshold]


def prepare(search: Sequence[Layer], refs: Sequence[Layer], ra: float, dec: float,
            pixscale: float) -> tuple[Cube, Planes, PassGeometry]:
    """Difference cube (reflected-sunlight template) and its matched-filter planes."""
    cube = difference_cube(search, refs)
    cube = cube.with_template(reflected_template(cube.wave_um))
    pl = planes(cube)
    return cube, pl, pass_geometry(ra, dec, cube.mjd, pixscale)


def run_core(search: Sequence[Layer], refs: Sequence[Layer], ra: float, dec: float,
             pixscale: float, with_null: bool = True,
             tgrid: TrajectoryGrid | None = None) -> CoreResult:
    """Full search (and, optionally, the mirrored null with the same trials)."""
    cube, pl, geom = prepare(search, refs, ra, dec, pixscale)
    tgrid = tgrid if tgrid is not None else trajectory_grid(geom)
    trials = make_trials(geom, tgrid)
    maps = run_search(pl, trials)
    dets = detect(pl, maps, trials, geom.dt, SEED_THRESHOLD)
    null: list[Detection] = []
    if with_null:
        nmaps = run_search(pl, trials, mirror=True)
        null = detect(pl, nmaps, trials, geom.dt, SEED_THRESHOLD, mirror=True)
    log.info("%d detections >= %.0f (null %d); >= %.0f: %d (null %d)", len(dets),
             SEED_THRESHOLD, len(null), THRESHOLD, sum(d.snr >= THRESHOLD for d in dets),
             sum(d.snr >= THRESHOLD for d in null))
    return CoreResult(cube, pl, geom, tgrid, trials, maps, tuple(dets), tuple(null))


def rate_of(core: CoreResult, d: Detection) -> tuple[float, float, float]:
    """(vx, vy) px/day and distance (au) of the trajectory behind a detection."""
    j = int(core.trials.rep[d.trial])
    return float(core.tgrid.vx[j]), float(core.tgrid.vy[j]), float(core.tgrid.d_au[j])


def frames_on_track(core: CoreResult, d: Detection) -> np.ndarray:
    """Boolean (n,) frames whose track position is on usable data."""
    _, phi = track_sums(core.planes, core.trials.offsets[d.trial], d.x, d.y)
    return phi > 0
