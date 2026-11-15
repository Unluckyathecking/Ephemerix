"""Choose which frames of a visit to read: the best ones, capped, before any byte is fetched.

Rank by frame quality (``qual_frame`` 10, then 5, then unknown), then whether the frame covers
the whole grid, then how far the target sits from the frame edge. The cap keeps deep-coverage
targets (R Dra has about 2,000 frames) cheap.
"""

from __future__ import annotations

from collections.abc import Sequence

from pxs.grid import Grid
from pxs.wise.frames import Frame
from pxs.wise.geometry import covers_grid, edge_distance_arcsec

DEFAULT_MAX_FRAMES = 16
UNKNOWN_QUALITY_RANK = 1  # below qual_frame 5, above the dropped qual_frame 0


def rank_frames(frames: Sequence[Frame], grid: Grid, ra: float, dec: float) -> list[Frame]:
    """Frames ordered best first for a target at (ra, dec) deg on ``grid``."""

    def score(f: Frame) -> tuple:
        qual = UNKNOWN_QUALITY_RANK if f.qual_frame is None else f.qual_frame
        return (-qual, not covers_grid(f.corners, grid),
                -edge_distance_arcsec(f.corners, ra, dec), f.key)

    return sorted(frames, key=score)


def choose_frames(frames: Sequence[Frame], grid: Grid, ra: float, dec: float,
                  max_frames: int = DEFAULT_MAX_FRAMES) -> list[Frame]:
    """The ``max_frames`` best usable frames (qual_frame 0 excluded), best first."""
    if max_frames < 1:
        raise ValueError(f"max_frames must be at least 1, got {max_frames}")
    usable = [f for f in frames if f.qual_frame != 0]
    return rank_frames(usable, grid, ra, dec)[:max_frames]
