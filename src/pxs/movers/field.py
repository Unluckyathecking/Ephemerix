"""Read one field and pass into grid layers (search frames plus reference frames).

Reading is the slow part (about 0.65 s per 20' stamp at 8 threads from the UK); stamps are
cached by pxs.spherex's stamp cache, so a second run of the same field reads nothing. The
layers are kept in memory so injections can rebuild only the search layers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pxs.grid import Grid
from pxs.spherex.read import Stamp
from pxs.spherex.types import Frame, Pass

from .frames import FieldPasses, field_passes
from .layers import Injector, Layer, field_grid, make_layer, read_stamps

log = logging.getLogger(__name__)

SEARCH_DETECTORS = (1, 2, 3)  # 0.75-2.42 um: reflected light; icy bodies are dark beyond
MIN_PASS_FRAMES = 10
MIN_REF_SEPARATION_DAYS = 60.0  # a reference pass must be long after the mover has gone
# Longest searched span. Passes are grouped by a 20-day gap, so one "pass" can join visits
# 44 days apart. The trajectory model (geometry.py) then errs by 0.5 px at 20 days and 1-2.5
# px at 28-44 days (straight-line barycentric bodies at 30-100 au, best-fit rate; measured
# by probes/movers/model_span.py), and the trial count grows as span^4 (7k at 9 days, 1.7M
# at 44). At 16 days the model error is <= 0.35 px, inside the grid's 0.5 px budget.
MAX_SPAN_DAYS = 16.0


@dataclass(frozen=True)
class FieldData:
    """Everything read for one field and pass. search_stamps are kept for injections."""

    grid: Grid
    search_pass: Pass
    search_stamps: tuple[tuple[Frame, Stamp], ...]
    refs: tuple[Layer, ...]
    search: tuple[Layer, ...]
    read_seconds: float
    n_ref_passes: int
    n_pass_frames: int = 0  # search-detector frames in the whole pass, before windowing

    @property
    def n_dropped(self) -> int:
        return max(self.n_pass_frames - len(self.search), 0)


def usable_passes(fp: FieldPasses) -> list[Pass]:
    return [p for p in fp.passes if len(p.frames) >= MIN_PASS_FRAMES]


def reference_frames(passes: list[Pass], chosen: Pass,
                     detectors: tuple[int, ...]) -> tuple[list[Frame], int]:
    """Frames of passes well separated in time from `chosen`, and how many passes they span."""
    mid = 0.5 * (chosen.mjd_start + chosen.mjd_end)
    others = [p for p in passes if p is not chosen
              and min(abs(p.mjd_start - mid), abs(p.mjd_end - mid)) > MIN_REF_SEPARATION_DAYS]
    return [f for p in others for f in p.frames if f.detector in detectors], len(others)


def search_window(frames: list[Frame], max_span_days: float = MAX_SPAN_DAYS) -> list[Frame]:
    """The frames in the window of at most max_span_days holding the most frames (the
    earliest such window on ties). All frames when the pass is already short enough."""
    fr = sorted(frames, key=lambda f: (f.mjd, f.detector))
    if not fr or fr[-1].mjd - fr[0].mjd <= max_span_days:
        return fr
    best, j = (0, 0), 0
    for i in range(len(fr)):
        while fr[i].mjd - fr[j].mjd > max_span_days:
            j += 1
        if i + 1 - j > best[1] - best[0]:
            best = (j, i + 1)
    return fr[best[0]:best[1]]


def load_field(ra: float, dec: float, size_arcmin: float, pass_index: int,
               detectors: tuple[int, ...] = SEARCH_DETECTORS) -> FieldData:
    """Read the search pass (index into the usable passes, oldest first) and its references.
    Only the densest MAX_SPAN_DAYS window of the pass is searched (search_window)."""
    t = time.time()
    grid = field_grid(ra, dec, size_arcmin)
    passes = usable_passes(field_passes(ra, dec))
    if not passes:
        raise ValueError("no SPHEREx pass covers this field")
    if not -len(passes) <= pass_index < len(passes):
        raise ValueError(f"pass index {pass_index} out of range: {len(passes)} usable passes")
    chosen = passes[pass_index]
    ref_frames, n_ref = reference_frames(passes, chosen, detectors)
    if not ref_frames:
        raise ValueError("no other pass of this field to build a static-sky reference from")
    # References are chosen against the whole pass object, so trimmed frames never become
    # part of the static-sky template.
    pass_frames = [f for f in chosen.frames if f.detector in detectors]
    search_frames = search_window(pass_frames)
    if len(search_frames) < len(pass_frames):
        log.info("pass spans %.1f d; searching %d of %d frames in %.1f d",
                 max(f.mjd for f in pass_frames) - min(f.mjd for f in pass_frames),
                 len(search_frames),
                 len(pass_frames), search_frames[-1].mjd - search_frames[0].mjd)
    stamps = read_stamps(search_frames + ref_frames, grid)
    keys = {f.s3_key for f in search_frames}
    s_st = tuple((f, s) for f, s in stamps if f.s3_key in keys)
    refs = tuple(make_layer(f, s, grid) for f, s in stamps if f.s3_key not in keys)
    search = tuple(make_layer(f, s, grid) for f, s in s_st)
    secs = time.time() - t
    log.info("field read: %d search + %d reference frames (%d passes) in %.0f s",
             len(search), len(refs), n_ref, secs)
    return FieldData(grid, chosen, s_st, refs, search, secs, n_ref, len(pass_frames))


def search_layers(fd: FieldData, inject: Injector | None) -> tuple[Layer, ...]:
    """The search layers, rebuilt with synthetic sources when `inject` is given."""
    if inject is None:
        return fd.search
    return tuple(make_layer(f, s, fd.grid, inject) for f, s in fd.search_stamps)
