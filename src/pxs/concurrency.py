"""Small concurrency helpers shared by the data path. Written with Claude Code.

- `irsa_slot()`: at most `IRSA_MAX_CONCURRENT` queries in flight to IRSA (SIA, TAP) from
  this process, whichever module asks. IRSA is a shared service that slows down under load.
- `map_ordered(fn, items, workers)`: `fn` over `items` on a thread pool, results in input
  order. The first exception (including BaseException such as a build cancellation) is
  re-raised after the pending items are cancelled; nothing is swallowed and the call does
  not wait for work that never started.
- `background(fn, *args)`: run `fn` on a daemon thread and return a Future, for optional
  lookups that may be abandoned (the process never waits for them at exit).
- `breaker(name)`: the process-wide record that an outside service ("irsa", "gaia") failed
  moments ago: a call that timed out or could not connect (`unreachable`) trips it for
  BREAKER_COOLDOWN_S, an answer closes it. It never skips a query: callers use `is_open()`
  only to ask an equivalent mirror at once instead of later (`catalogs.overlays`), so no
  lookup gets less data than it would without it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager, contextmanager
from typing import TypeVar

import requests

T = TypeVar("T")
R = TypeVar("R")

IRSA_MAX_CONCURRENT = 4
_irsa = threading.BoundedSemaphore(IRSA_MAX_CONCURRENT)


@contextmanager
def irsa_slot() -> Iterator[None]:
    """Hold one of the process-wide IRSA query slots for the duration of the block."""
    with _irsa:
        yield


BREAKER_COOLDOWN_S = 180.0


class Breaker:
    """Whether one service failed moments ago. Thread-safe; see the module docstring."""

    def __init__(self, name: str, cooldown_s: float = BREAKER_COOLDOWN_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.name, self._cooldown, self._clock = name, cooldown_s, clock
        self._open_until: float | None = None  # None: closed
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            return self._open_until is not None and self._clock() < self._open_until

    def trip(self) -> None:
        with self._lock:
            self._open_until = self._clock() + self._cooldown

    def reset(self) -> None:
        with self._lock:
            self._open_until = None


_breakers: dict[str, Breaker] = {}
_breakers_lock = threading.Lock()


def breaker(name: str) -> Breaker:
    """The process-wide breaker for service `name`."""
    with _breakers_lock:
        return _breakers.setdefault(name, Breaker(name))


def reset_breakers() -> None:
    """Close every breaker (tests). Breakers are reset in place, so modules holding one keep
    a valid reference."""
    with _breakers_lock:
        for b in _breakers.values():
            b.reset()


def unreachable(exc: BaseException, read_timeout_counts: bool = True) -> bool:
    """True for failures that mean the service is not answering at all: no connection, a
    dropped one, or (unless `read_timeout_counts` is False, for queries that are routinely
    slower than their own timeout) no answer in time. False for an HTTP error status or a
    bad answer."""
    if isinstance(exc, requests.ReadTimeout):
        return read_timeout_counts
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def limited(n: int) -> Callable[[], AbstractContextManager[None]]:
    """A context-manager factory allowing at most `n` holders at once (a sub-limit, e.g. for
    optional queries inside the IRSA limit)."""
    sem = threading.BoundedSemaphore(n)

    @contextmanager
    def slot() -> Iterator[None]:
        with sem:
            yield

    return slot


def map_ordered(fn: Callable[[T], R], items: Sequence[T], workers: int,
                name: str = "pxs-map") -> list[R]:
    """[fn(x) for x in items], run on up to `workers` threads; see the module docstring."""
    if workers < 1:
        raise ValueError(f"workers must be at least 1, got {workers}")
    if len(items) <= 1 or workers == 1:
        return [fn(x) for x in items]
    ex = ThreadPoolExecutor(max_workers=min(workers, len(items)), thread_name_prefix=name)
    try:
        futures = [ex.submit(fn, x) for x in items]
        done, _ = wait(futures, return_when=FIRST_EXCEPTION)
        failed = next((f for f in futures if f in done and f.exception() is not None), None)
        if failed is not None:
            for f in futures:
                f.cancel()
            raise failed.exception()  # type: ignore[misc]
        return [f.result() for f in futures]
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def background(fn: Callable[..., R], *args: object) -> Future[R]:
    """Start fn(*args) on a daemon thread; its result or exception lands in the Future."""
    fut: Future[R] = Future()

    def run() -> None:
        if not fut.set_running_or_notify_cancel():
            return
        try:
            fut.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001 - handed to whoever reads the Future
            fut.set_exception(exc)

    threading.Thread(target=run, daemon=True, name=f"pxs-bg-{getattr(fn, '__name__', 'fn')}").start()
    return fut
