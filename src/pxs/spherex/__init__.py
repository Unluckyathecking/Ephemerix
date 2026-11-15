"""SPHEREx Level-2 data: find frames, group passes, stack images, extract spectra.

Interface:
    find_frames(ra, dec, radius_deg=..., collections=COLLECTIONS) -> list[Frame]
    group_passes(frames) -> list[Pass]
    stack_pass(pas, grid, window_um, target=None) -> Stack | None
    extract_spectrum(pas, target, neighbours=None) -> list[SpecPoint]
    prefetch_pass(pas, grid, target) -> Prefetched   # optional: read each frame once for both
    warm_from_index(target, grid) -> int  # optional: prefetch indexed frames during the search

Written with Claude Code.
"""

from pxs.procs import offloaded

from . import spectrum as _spectrum
from . import stack as _stack
from .config import COLLECTIONS, DEEP_COLLECTIONS
from .prefetch import prefetch_pass, warm_from_index
from .query import find_frames, find_frames_for_target, group_passes, search_circle

# CPU-heavy: in a worker process when PXS_PROCESSES is set (pxs.procs), else in-process.
stack_pass = offloaded(_stack.stack_pass)
extract_spectrum = offloaded(_spectrum.extract_spectrum)
from .types import Frame, Pass, SpecPoint, Target

__all__ = [
    "COLLECTIONS", "DEEP_COLLECTIONS", "Frame", "Pass", "SpecPoint", "Target",
    "extract_spectrum", "find_frames", "find_frames_for_target", "group_passes", "prefetch_pass",
    "search_circle", "stack_pass", "warm_from_index",
]
