"""Progress reporting and cooperative cancellation for one build.

Python cannot stop a thread from outside, so a build is cancelled by raising
`BuildCancelled` at its next progress report or data-module call. It derives from
BaseException so the `except Exception` blocks in `pxs.sources` do not swallow it.

The WISE and SPHEREx sources run at the same time, each on several threads. Each wrapper
reports its own share done (0-1) to a `Combined`, which turns the two into one fraction
(weighted, monotonic) and a stage text naming what is still in flight, e.g.
"Reading WISE images (12 of 46); reading SPHEREx images (310 of 452)".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from pxs.api.warmup import MISS, Warmup, spectrum_key, stack_key
from pxs.grid import Grid, Stack
from pxs.sources import SPHEREX_WINDOWS

Report = Callable[[str, float], None]

WISE_SPAN = (0.02, 0.45)
SPHEREX_SPAN = (0.45, 0.8)
DATA_SPAN = (0.02, 0.8)  # both sources together, when they run at once
# Rough share of the data time each source takes on a cold build; only shapes the bar.
WEIGHTS = {"wise": 0.35, "spherex": 0.65}
READ_SHARE = 0.85  # share of the SPHEREx part spent reading frames when it prefetches


class BuildCancelled(BaseException):
    """Raised inside a build thread once its job was cancelled or timed out."""


class Tracker:
    """Holds a job's current stage and fraction and its cancel flag. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.deadline: float | None = None  # set when the build starts; checked at each report
        self._clock = clock
        self.stage = "Waiting for a free worker"
        self.fraction = 0.0
        self.cancelled = threading.Event()
        self._lock = threading.Lock()

    def report(self, stage: str, fraction: float) -> None:
        if self.deadline is not None and self._clock() >= self.deadline:
            self.cancelled.set()
        if self.cancelled.is_set():
            raise BuildCancelled
        with self._lock:
            self.stage = stage
            self.fraction = max(self.fraction, min(1.0, max(0.0, fraction)))

    def snapshot(self) -> tuple[str, float]:
        with self._lock:
            return self.stage, self.fraction


class Combined:
    """Merges the reports of parts running at once into one stage text and fraction."""

    def __init__(self, report: Report, span: tuple[float, float] = DATA_SPAN,
                 weights: dict[str, float] | None = None) -> None:
        self._report, self._span = report, span
        self._weights = dict(weights or WEIGHTS)
        self._state: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def part(self, name: str) -> Report:
        """A Report for one part; its fraction is that part's own share done (0-1)."""
        if name not in self._weights:
            raise ValueError(f"unknown part {name!r}")

        def report(stage: str, fraction: float) -> None:
            with self._lock:
                old = self._state.get(name, ("", 0.0))[1]
                self._state[name] = (stage, max(old, min(1.0, max(0.0, fraction))))
                busy = [s for s, f in self._state.values() if f < 1.0 and s]
                text = "; ".join([busy[0]] + [b[0].lower() + b[1:] for b in busy[1:]]) \
                    if busy else stage
                total = sum(self._weights.values())
                done = sum(self._weights[n] * f for n, (_, f) in self._state.items()) / total
            self._report(text, self._span[0] + (self._span[1] - self._span[0]) * done)

        return report


def _within(span: tuple[float, float], done: float, total: int) -> float:
    return span[0] + (span[1] - span[0]) * (done / total if total else 0.0)


class WiseProgress:
    """Wraps a WISE source: reports per stack and checks for cancellation on every call.

    Thread-safe: `stack_visit` may be called from several threads at once."""

    def __init__(self, inner: Any, report: Report, span: tuple[float, float] = WISE_SPAN) -> None:
        self._inner, self._report, self._span = inner, report, span
        self._total, self._done = 0, 0
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        # Optional helpers of the data module (e.g. path_from_motion) pass straight through.
        if name == "path_from_motion":
            return getattr(self._inner, name)
        raise AttributeError(name)

    def find_visits(self, ra: float, dec: float, **kwargs: Any) -> list[Any]:
        self._report("Searching WISE frames", self._span[0])
        try:
            visits = self._inner.find_visits(ra, dec, **kwargs)
        except Exception:
            self._report("WISE search failed", self._span[1])  # no longer shown as running
            raise
        self._total = 2 * len(visits)
        if not visits:
            self._report("No WISE visits", self._span[1])
        return visits

    def _progress(self) -> tuple[str, float]:
        with self._lock:
            done, total = self._done, self._total
        return (f"Reading WISE images ({done} of {total})" if done < total else "WISE images read",
                _within(self._span, done, total))

    def stack_visit(self, visit: Any, band: str, grid: Grid) -> Stack | None:
        self._report(*self._progress())  # also the cancellation check
        try:
            return self._inner.stack_visit(visit, band, grid)
        finally:
            with self._lock:
                self._done += 1
            self._report(*self._progress())


class SpherexProgress:
    """Wraps a SPHEREx source the same way: one step per window stack and per spectrum and,
    when the module can prefetch a pass, one tick per frame read. Thread-safe."""

    def __init__(self, inner: Any, report: Report,
                 span: tuple[float, float] = SPHEREX_SPAN) -> None:
        self._inner, self._report, self._span = inner, report, span
        self._total, self._started, self._finished = 0, 0, 0
        self._frames_total = 0
        self._frames: dict[int, int] = {}  # frames read so far, per pass
        self._warmup: Warmup | None = None
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        # Mover-aware search and the pass prefetch of the data module, when it has them.
        if name == "find_frames_for_target" and hasattr(self._inner, name):
            return self._find_frames_for_target
        if name == "prefetch_pass" and hasattr(self._inner, name):
            return self._prefetch_pass
        raise AttributeError(name)

    def _fraction(self) -> float:
        with self._lock:
            steps = self._finished / self._total if self._total else 0.0
            if not self._frames_total:
                return _within(self._span, steps, 1)
            read = sum(self._frames.values()) / self._frames_total
        return _within(self._span, READ_SHARE * read + (1 - READ_SHARE) * steps, 1)

    def warm(self, grid: Grid, target: Any, neighbours: Callable[[Any], Any] | None = None) -> None:
        """Start the SPHEREx head start (`pxs.api.warmup`) if the data module can warm from
        its index: indexed frames are read, stacked and measured while the archive search
        runs, and the build's identical calls below are served from it. Reports "Reading
        SPHEREx images (n of N)" meanwhile."""
        if getattr(self._inner, "warm_from_index", None) is None:
            return

        def on_frame(done: int, total: int) -> None:
            self._report(f"Reading SPHEREx images ({done} of {total})",
                         _within(self._span, READ_SHARE * done / total, 1))

        self._warmup = Warmup(self._inner)
        self._warmup.start(grid, target, neighbours, on_frame)

    def _find_frames_for_target(self, target: Any) -> list[Any]:
        self._report("Searching SPHEREx frames", self._span[0])
        return self._searching(lambda: self._inner.find_frames_for_target(target))

    def find_frames(self, ra: float, dec: float) -> list[Any]:
        self._report("Searching SPHEREx frames", self._span[0])
        return self._searching(lambda: self._inner.find_frames(ra, dec))

    def _searching(self, call: Callable[[], list[Any]]) -> list[Any]:
        try:
            return call()
        except Exception:
            self._report("SPHEREx search failed", self._span[1])  # no longer shown as running
            raise

    def group_passes(self, frames: list[Any]) -> list[Any]:
        passes = self._inner.group_passes(frames)
        with self._lock:
            self._total = (len(SPHEREX_WINDOWS) + 1) * len(passes)  # stacks plus one spectrum
            if hasattr(self._inner, "prefetch_pass"):
                self._frames_total = sum(len(p.frames) for p in passes)
        if not passes:
            self._report("No SPHEREx passes", self._span[1])
        return passes

    def _prefetch_pass(self, pas: Any, grid: Grid, target: Any = None) -> Any:
        key = id(pas)

        def on_frame(done: int, total: int) -> None:
            with self._lock:
                self._frames[key] = done
                n, of = sum(self._frames.values()), self._frames_total
            self._report(f"Reading SPHEREx images ({n} of {of})", self._fraction())

        if self._warmup is not None:
            self._warmup.wait_reads()  # never read a frame twice
        self._report("Reading SPHEREx images", self._fraction())
        return self._inner.prefetch_pass(pas, grid, target, on_frame=on_frame)

    def _step(self, what: str, call: Callable[[], Any]) -> Any:
        with self._lock:
            self._started += 1
            n, total = self._started, self._total
        self._report(f"{what} ({n} of {total})", self._fraction())
        try:
            return call()
        finally:
            with self._lock:
                self._finished += 1
                last = self._finished == self._total
            if last:
                self._report("SPHEREx images and spectra done", self._span[1])

    def _warm_or(self, key: Any, call: Callable[[], Any]) -> Any:
        got = MISS if self._warmup is None else self._warmup.get(key)
        return call() if got is MISS else got

    def stack_pass(self, pas: Any, grid: Grid, window_um: tuple[float, float],
                   target: Any = None) -> Stack | None:
        return self._step("Stacking SPHEREx images", lambda: self._warm_or(
            stack_key(pas, grid, window_um, target),
            lambda: self._inner.stack_pass(pas, grid, window_um, target)))

    def extract_spectrum(self, pas: Any, target: Any, **kwargs: Any) -> list[Any]:
        return self._step("Measuring the SPHEREx spectrum", lambda: self._warm_or(
            spectrum_key(pas, target, kwargs.get("neighbours")),
            lambda: self._inner.extract_spectrum(pas, target, **kwargs)))
