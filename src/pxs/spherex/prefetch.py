"""Read every exposure of a pass once, for both the window stacks and the spectrum.

`stack_pass` (one call per window) wants a large stamp at the grid centre without PSF;
`extract_spectrum` wants a small stamp with PSF at the target's position on that date.
Read separately, each frame's FITS headers were walked and its rows fetched two or three
times, eight frames at a time. `prefetch_pass` opens each frame once, cuts both stamps
from one prefetched batch of byte ranges (`read.read_stamps`), and puts them in the stamp
cache, PASS_WORKERS frames at a time; the later `stack_pass`/`extract_spectrum` calls then
find every stamp in memory. The stamps are bit-for-bit what those calls would have read.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pxs import procs
from pxs.concurrency import map_ordered
from pxs.grid import Grid

from . import config, stampcache
from .net import BlockStore
from .read import Request, read_stamps
from .stack import stamp_half
from .stamps import position_at
from .types import Frame, Pass, Target

log = logging.getLogger(__name__)

OnFrame = Callable[[int, int], None]  # (frames done, frames in the pass)
CHUNK_FRAMES = 8  # frames per worker-process call when PXS_PROCESSES is on


@dataclass(frozen=True)
class Prefetched:
    """Frames read (or already cached) and frames that failed; failures are retried later
    by the normal read path, which counts and reports them as before."""

    n_frames: int
    n_failed: int


def requests_for(frame: Frame, grid: Grid, target: Target | None) -> list[Request]:
    """The stamps the build reads from `frame`: the stack stamp at the grid centre and,
    with a target, the spectrum stamp at its position (as `spectrum.extract_spectrum`)."""
    out = [Request(grid.center_ra, grid.center_dec, stamp_half(grid), False)]
    if target is not None:
        out.append(Request(*position_at(target, frame.mjd), config.STAMP_HALF, True))
    return out


def _missing(frame: Frame, reqs: list[Request]) -> list[Request]:
    return [r for r in reqs
            if stampcache.get(frame.s3_key, r.ra, r.dec, r.half, r.with_psf) is stampcache.MISS]


def _read(frame: Frame, reqs: list[Request], store: BlockStore | None) -> None:
    if store is not None or config.byte_cache_enabled():
        stamps = read_stamps(store or BlockStore(), frame.s3_key, reqs)
    else:
        with tempfile.TemporaryDirectory(prefix="pxs-blocks-") as tmp:
            stamps = read_stamps(BlockStore(root=Path(tmp)), frame.s3_key, reqs)
    for r, s in zip(reqs, stamps):
        stampcache.put(frame.s3_key, r.ra, r.dec, r.half, r.with_psf, s)


def _one(frame: Frame, grid: Grid, target: Target | None, store: BlockStore | None) -> bool:
    """Read and cache what is missing for one frame; False if it could not be read."""
    reqs = _missing(frame, requests_for(frame, grid, target))
    if not reqs:
        return True
    try:
        _read(frame, reqs, store)
    except Exception as e:  # noqa: BLE001 - read_many retries and counts it later
        log.warning("prefetch of %s D%d failed: %s", frame.obs_id, frame.detector, e)
        return False
    return True


def prefetch_frames(frames: list[Frame], grid: Grid, target: Target | None,
                    workers: int = CHUNK_FRAMES) -> int:
    """Prefetch a few frames on threads; returns how many failed. Runs in a worker process
    when PXS_PROCESSES is on (see `prefetch_pass`), so it takes no callback or store."""
    return sum(not ok for ok in map_ordered(lambda f: _one(f, grid, target, None), frames,
                                            workers, name="pxs-spx-read"))


_prefetch_in_worker = procs.offloaded(prefetch_frames, pool="io")


def prefetch_pass(pas: Pass, grid: Grid, target: Target | None = None,
                  on_frame: OnFrame | None = None, store: BlockStore | None = None,
                  workers: int = config.PASS_WORKERS) -> Prefetched:
    """Read and cache every stamp the build will want from this pass, each frame once.

    `on_frame(done, total)` is called as frames finish (per frame, or per chunk of
    CHUNK_FRAMES when the reads run in worker processes); an exception it raises (e.g. a
    build cancellation) stops the prefetch and propagates. A frame that cannot be read is
    logged and left for the normal read path.
    """
    lock, done = threading.Lock(), [0]
    frames = list(pas.frames)
    total = len(frames)

    def tick(n_frames: int) -> None:
        with lock:
            done[0] += n_frames
            n = done[0]
        if on_frame is not None:
            on_frame(n, total)

    if procs.workers() and store is None:  # CPU-heavy header parsing: use every core
        chunks = [frames[i:i + CHUNK_FRAMES] for i in range(0, total, CHUNK_FRAMES)]

        def chunk(fs: list[Frame]) -> int:
            failed = _prefetch_in_worker(fs, grid, target)
            tick(len(fs))
            return failed

        n_failed = sum(map_ordered(chunk, chunks, max(1, workers // CHUNK_FRAMES * 2),
                                   name="pxs-spx-chunk"))
        return Prefetched(total, n_failed)

    def one(frame: Frame) -> bool:
        ok = _one(frame, grid, target, store)
        tick(1)
        return ok

    results = map_ordered(one, frames, workers, name="pxs-spx-read")
    return Prefetched(total, sum(not ok for ok in results))


WARM_PASSES = 4  # passes warmed at once, as pxs.sources.PASS_PARALLEL


def warm_from_index(target: Target, grid: Grid,
                    on_frame: OnFrame | None = None) -> list[Pass]:
    """Prefetch the stamps of the frames our own index lists for `target`, while the IRSA
    search for frames newer than the index (PXS_SPHEREX_INDEX_SIA_TAIL) is still out.

    Only fills the stamp cache, which holds exactly what the build's own reads would get, so
    the view is unchanged: the build still groups passes from the full frame list (index plus
    IRSA's newer frames) and reads whatever is not cached yet. Returns the passes of the
    indexed frames (as `group_passes` makes them), or [] when there is no index or no IRSA
    search to overlap with. `on_frame(done, total)` counts frames over all passes.
    """
    from . import localindex, query  # here, not at import: query imports this package's net

    local = localindex.try_lookup(*query.search_circle(target), config.COLLECTIONS)
    if local is None or local.sia_after_mjd is None or not local.frames:
        return []
    passes = query.group_passes(local.frames)
    total = len(local.frames)
    lock, counted = threading.Lock(), {}  # frames done, per pass

    def run(p: Pass) -> None:
        def on_pass_frame(n: int, _of: int) -> None:
            with lock:
                counted[id(p)] = n
                now = sum(counted.values())
            if on_frame is not None:
                on_frame(now, total)

        prefetch_pass(p, grid, target, on_frame=on_pass_frame)

    map_ordered(run, passes, WARM_PASSES, name="pxs-spx-warm")
    return passes
