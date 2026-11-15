"""Frames of one field: the pass to search and, per frame, wavelength-matched reference frames
from the other passes (the static-sky template; a distant body moves > 1 deg between passes).

IRSA SIA intermittently returns 502 or times out (seen 14 Nov 2026), so queries are retried
here with backoff on top of pxs.spherex's own single retry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from pxs.spherex.config import COLLECTIONS
from pxs.spherex.query import find_frames, group_passes
from pxs.spherex.types import Frame, Pass

log = logging.getLogger(__name__)

DETECTORS = (1, 2, 3, 4)  # 0.75-3.82 um; D5-D6 (3.8-5 um) add little for these bodies
SIA_ATTEMPTS = 6
SIA_BACKOFF_S = 3.0


def _one_collection(ra: float, dec: float, coll: str, attempts: int) -> list[Frame]:
    # One collection per call: find_frames only raises when every collection fails, so a
    # multi-collection call would silently drop a failed one instead of retrying it.
    for i in range(attempts):
        try:
            return find_frames(ra, dec, collections=(coll,))
        except RuntimeError as e:
            if i == attempts - 1:
                raise
            log.info("SIA %s failed (%s); retry %d in %.0f s", coll, e, i + 1,
                     SIA_BACKOFF_S * (i + 1))
            time.sleep(SIA_BACKOFF_S * (i + 1))
    raise AssertionError("unreachable")


def frames_with_retry(ra: float, dec: float, attempts: int = SIA_ATTEMPTS) -> list[Frame]:
    """find_frames at a point (frames whose footprint contains it), each collection retried."""
    frames = [f for c in COLLECTIONS for f in _one_collection(ra, dec, c, attempts)]
    return sorted(frames, key=lambda f: (f.mjd, f.detector))


@dataclass(frozen=True)
class FieldPasses:
    """All passes over a field centre, restricted to the searched detectors."""

    passes: tuple[Pass, ...]

    def pick(self, index: int) -> Pass:
        if not -len(self.passes) <= index < len(self.passes):
            raise ValueError(f"pass index {index} out of range ({len(self.passes)} passes)")
        return self.passes[index]

    def others(self, index: int) -> tuple[Frame, ...]:
        """Frames of every pass except `index`: candidates for the static-sky reference."""
        chosen = self.pick(index)
        return tuple(f for p in self.passes if p is not chosen for f in p.frames)


def field_passes(ra: float, dec: float, detectors: Sequence[int] = DETECTORS) -> FieldPasses:
    """Passes over (ra, dec), with frames from `detectors` only, oldest first."""
    frames = [f for f in frames_with_retry(ra, dec) if f.detector in detectors]
    return FieldPasses(tuple(group_passes(frames)))


def pass_containing(fp: FieldPasses, mjd: float, slack_days: float = 3.0) -> int:
    """Index of the pass whose time span contains mjd (within slack_days)."""
    for i, p in enumerate(fp.passes):
        if p.mjd_start - slack_days <= mjd <= p.mjd_end + slack_days:
            return i
    raise ValueError(f"no pass covers MJD {mjd:.1f}")
