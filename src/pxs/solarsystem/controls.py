"""Background controls: the same photometry at the same sky positions when the body is gone.

For a pass, positions are sampled evenly in time along the body's track. At each, SIA finds
the frames from the body's other passes (the body is then degrees away) and forced PSF
photometry is run there exactly as on the body. The combined control flux per detector
band is what a static background (faint stars, galaxies, residual background bias) adds at
the track; the body's flux is reported as body minus control.

Units: mJy, degrees, MJD.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pxs.spherex import config as spx_config
from pxs.spherex.types import Frame, SpecPoint

from .horizons import EphemPoint
from .phot import BandFlux, all_bands, measure_pass, read_visits
from .track import Visit, sia_frames, usable_index

log = logging.getLogger(__name__)

N_POSITIONS = 8
PER_DETECTOR = 3  # control frames per detector per position
EXCLUDE_DAYS = 2.0  # frames this close to the pass in time are never used as controls


@dataclass(frozen=True)
class Control:
    """Control photometry for one pass: per-band fluxes, points used, frames tried."""

    bands: tuple[BandFlux, ...]
    points: tuple[SpecPoint, ...]
    n_positions: int
    n_frames: int


def sample_track(visits: Sequence[Visit], n: int = N_POSITIONS) -> list[EphemPoint]:
    """n ephemeris points spread evenly in time over the pass."""
    ordered = sorted(visits, key=lambda v: v.frame.mjd)
    if not ordered:
        return []
    idx = sorted({round(i * (len(ordered) - 1) / max(n - 1, 1)) for i in range(n)})
    return [ordered[i].eph for i in idx]


def frames_at(ra: float, dec: float) -> list[Frame]:
    """Frames covering a sky position: from the local frame index alone when it is usable
    (controls need no frames newer than the index, so no SIA tail), else from SIA."""
    idx = usable_index()
    if idx is not None:
        return idx.find([(ra, dec)], spx_config.POINT_RADIUS_DEG, spx_config.COLLECTIONS)
    return sia_frames(ra, dec) or []


def control_frames(pos: EphemPoint, mjd_lo: float, mjd_hi: float,
                   per_detector: int = PER_DETECTOR) -> list[Frame]:
    """Up to `per_detector` frames per detector at `pos`, outside [mjd_lo, mjd_hi] +- margin."""
    frames = [f for f in frames_at(pos.ra, pos.dec)
              if not (mjd_lo - EXCLUDE_DAYS <= f.mjd <= mjd_hi + EXCLUDE_DAYS)]
    out: list[Frame] = []
    for det in sorted({f.detector for f in frames}):
        sub = [f for f in frames if f.detector == det]
        step = max(1, len(sub) // per_detector)
        out += sub[::step][:per_detector]
    return out


def run_control(visits: Sequence[Visit], half: int) -> Control:
    """Control photometry at the pass's track positions in the body's other passes."""
    if not visits:
        return Control((), (), 0, 0)
    lo = min(v.frame.mjd for v in visits)
    hi = max(v.frame.mjd for v in visits)
    positions = sample_track(visits)
    with ThreadPoolExecutor(max_workers=2) as ex:
        found = list(ex.map(lambda p: control_frames(p, lo, hi), positions))
    # A control "visit" pins the body's ephemeris row to a fixed sky position.
    jobs = [Visit(f, p) for p, fs in zip(positions, found) for f in fs]
    read, failed = read_visits(jobs, half)
    if failed:
        log.warning("control: %d frames could not be read", failed)
    points = tuple(m.point for m in measure_pass(read))
    return Control(tuple(all_bands(points)), points, len(positions), len(jobs))
