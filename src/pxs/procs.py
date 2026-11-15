"""Run CPU-heavy data-module calls in worker processes. Written with Claude Code.

A view build does most of its work in Python (FITS header parsing, WCS with SIP,
resampling, PSF fits) on threads, so the GIL holds it to about two busy cores however many
the machine has. `offloaded(fn)` wraps a module-level function so that, when worker
processes are enabled, each call runs in a shared process pool and the calling thread just
waits for the result. Arguments and results are pickled (frames, grids, stacks and spectrum
points are small dataclasses and arrays); exceptions come back as raised.

Two pools of that size: "cpu" for pure computation (stacks and spectra from cached stamps)
and "io" for calls that also wait on the network (frame reads with header parsing), so a
worker blocked on a download never holds back computation that is ready to run.

Off unless PXS_PROCESSES is set to a positive number of workers (the service sets it), so
tests and the CLI keep running everything in-process, where monkeypatching works. Workers
start with the "forkserver" method (the parent has many threads, so plain fork is unsafe)
and never start pools of their own. A broken pool (a worker killed, e.g. out of memory) is
replaced on the next call; the call that saw it runs in-process instead.
"""

from __future__ import annotations

import functools
import logging
import multiprocessing as mp
import os
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import ParamSpec, TypeVar

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

ENV = "PXS_PROCESSES"
PRELOAD = ["pxs.spherex", "pxs.wise"]  # imported once in the fork server, not per worker

POOLS = ("cpu", "io")
_pools: dict[str, ProcessPoolExecutor] = {}
_lock = threading.Lock()


def workers() -> int:
    """Worker processes to use (0: run in-process). From PXS_PROCESSES."""
    try:
        return max(0, int(os.environ.get(ENV, "0") or 0))
    except ValueError:
        log.warning("ignoring %s=%r: not a number", ENV, os.environ.get(ENV))
        return 0


def _init_worker() -> None:
    os.environ[ENV] = "0"  # a worker runs its calls in-process
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def _get_pool(name: str, n: int) -> ProcessPoolExecutor:
    with _lock:
        if name not in _pools:
            ctx = mp.get_context("forkserver")
            ctx.set_forkserver_preload(PRELOAD)
            _pools[name] = ProcessPoolExecutor(max_workers=n, mp_context=ctx,
                                               initializer=_init_worker)
            log.info("started %d %s worker processes", n, name)
        return _pools[name]


def _drop_pool(name: str, broken: ProcessPoolExecutor) -> None:
    with _lock:
        if _pools.get(name) is broken:
            del _pools[name]
    broken.shutdown(wait=False, cancel_futures=True)


def offloaded(fn: Callable[P, R], pool: str = "cpu") -> Callable[P, R]:
    """`fn`, run in a worker process of `pool` ("cpu" or "io") when PXS_PROCESSES > 0.
    `fn` must be importable by name (a module-level function) and its arguments and
    result picklable."""
    if pool not in POOLS:
        raise ValueError(f"pool must be one of {POOLS}, got {pool!r}")

    @functools.wraps(fn)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        n = workers()
        if n == 0:
            return fn(*args, **kwargs)
        executor = _get_pool(pool, n)
        try:
            return executor.submit(fn, *args, **kwargs).result()
        except BrokenProcessPool:
            log.error("worker pool broke during %s; running it in-process", fn.__qualname__)
            _drop_pool(pool, executor)
            return fn(*args, **kwargs)

    return call


def shutdown() -> None:
    """Stop the worker processes (tests and shutdown)."""
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.shutdown(wait=True, cancel_futures=True)
