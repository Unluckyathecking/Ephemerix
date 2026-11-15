"""SPHEREx head start: work on the frames our own index lists while IRSA's search runs.

With PXS_SPHEREX_INDEX_SIA_TAIL on, the SPHEREx frame list is the index's answer (instant)
plus IRSA's answer for frames newer than the index (often 20-60 s). The build cannot group
passes before it has the full list, but every pass made only of indexed frames comes out the
same either way. So, meanwhile, `Warmup` reads those frames (`warm_from_index` of the data
module, which only fills the stamp cache) and then stacks and measures each indexed pass.
The build's own calls for a pass with exactly the same frames and arguments are then served
from these results; any other call (a pass IRSA's newer frames changed, a failed warm call)
is computed as before. The calls are deterministic, so the view is unchanged.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Hashable, Sequence
from concurrent.futures import Future
from typing import Any

from pxs.concurrency import background, map_ordered
from pxs.grid import Grid
from pxs.sources import PASS_PARALLEL, SPHEREX_WINDOWS

log = logging.getLogger(__name__)

OnFrame = Callable[[int, int], None]
Neighbours = Callable[[Any], Any]  # pass -> neighbour list or None (as pxs.build gives)
MISS = object()


def neighbours_key(nb: Sequence[Sequence[float]] | None) -> Hashable:
    return None if nb is None else tuple(tuple(p) for p in nb)


def stack_key(pas: Any, grid: Grid, window_um: tuple[float, float], target: Any) -> Hashable:
    return ("stack", pas, grid, tuple(window_um), id(target))


def spectrum_key(pas: Any, target: Any, nb: Sequence[Sequence[float]] | None) -> Hashable:
    return ("spectrum", pas, id(target), neighbours_key(nb))


class Warmup:
    """Runs the head start for one build and serves its results. Thread-safe."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._reads_done = threading.Event()
        self._results: dict[Hashable, Future] = {}
        self._lock = threading.Lock()

    def start(self, grid: Grid, target: Any, neighbours: Neighbours | None,
              on_frame: OnFrame | None = None) -> Future:
        """Start the head start on a daemon thread; the Future ends with it (passes done)."""
        self.job = background(self._run, grid, target, neighbours, on_frame)
        return self.job

    def _run(self, grid: Grid, target: Any, neighbours: Neighbours | None,
             on_frame: OnFrame | None) -> int:
        try:
            passes = self._inner.warm_from_index(target, grid, on_frame)
        finally:
            self._reads_done.set()
        jobs: list[tuple[Hashable, Callable[[], Any]]] = []
        for pas in passes:
            for window in SPHEREX_WINDOWS.values():
                jobs.append((stack_key(pas, grid, window, target),
                             lambda p=pas, w=window: self._inner.stack_pass(p, grid, w, target)))
            jobs.append((None, lambda p=pas: self._spectrum(p, target, neighbours)))
        with self._lock:
            futures = {k: self._results.setdefault(k, Future()) for k, _ in jobs if k}
        try:
            map_ordered(lambda job: self._settle(futures.get(job[0]), job[1]), jobs,
                        PASS_PARALLEL * (len(SPHEREX_WINDOWS) + 1), name="pxs-spx-warmcalc")
        finally:  # nothing may be left for the build to wait on forever
            with self._lock:
                left = [f for f in self._results.values() if not f.done()]
            for f in left:
                f.set_exception(RuntimeError("SPHEREx warm-up stopped"))
        return len(passes)

    def _spectrum(self, pas: Any, target: Any, neighbours: Neighbours | None) -> None:
        try:
            nb = None if neighbours is None else neighbours(pas)
        except Exception:  # the build asks for this spectrum itself
            log.exception("neighbours for the SPHEREx warm-up failed")
            return
        with self._lock:
            fut = self._results.setdefault(spectrum_key(pas, target, nb), Future())
        self._settle(fut, lambda: (self._inner.extract_spectrum(pas, target) if nb is None else
                                   self._inner.extract_spectrum(pas, target, neighbours=nb)))

    @staticmethod
    def _settle(fut: Future | None, call: Callable[[], Any]) -> None:
        if fut is None:  # the spectrum job registers its own key once it knows the neighbours
            call()
            return
        if not fut.set_running_or_notify_cancel():
            return
        try:
            fut.set_result(call())
        except BaseException as exc:  # noqa: BLE001 - the build recomputes this one itself
            fut.set_exception(exc)

    def wait_reads(self) -> None:
        """Block until the warm reads are over, so the build never reads a frame twice."""
        self._reads_done.wait()

    def get(self, key: Hashable) -> Any:
        """The warm result for `key` (waiting if it is being computed), or MISS."""
        with self._lock:
            fut = self._results.get(key)
        if fut is None:
            return MISS
        try:
            return fut.result()
        except BaseException:  # noqa: BLE001 - failed or cancelled warm call: compute it again
            return MISS
