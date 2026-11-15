"""Build jobs: one per cache key, a bounded worker pool, a queue cap and a hard timeout.

Each job runs on a pool thread (the slot) which starts the build on its own thread and
waits at most the timeout for it. The build also carries a deadline that its progress
reports check, so a build that is merely slow between calls stops by itself. On timeout the
job is reported as failed at once and cancelled, and the slot is released even if the
build thread is still blocked in a network call (a thread cannot be killed). Such an
abandoned thread no longer counts against `max_builds`; abandoned threads are counted and
capped: at the cap new builds are refused and the service reports itself unhealthy.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from pxs.api.cache import ViewCache
from pxs.api.degraded import is_degraded
from pxs.api.progress import BuildCancelled, Report, Tracker
from pxs.build import BuildError

log = logging.getLogger("pxs.api.jobs")



class JobParams(Protocol):
    """What a job needs from its request: the cache key (ViewParams or BodyParams)."""

    @property
    def key(self) -> str: ...


BuildFn = Callable[[Any, Path, Report], dict]

NO_DATA = "No WISE or SPHEREx images could be found for this position, so no view was built."
SERVER_FAULT = "The view could not be built because of a problem on the server. Try again later."


class QueueFull(RuntimeError):
    """Too many builds are waiting; the caller should retry later."""


class AuthoredFailure(Exception):
    """A build that cannot produce a view, with a sentence written in this codebase for the
    user. Only raise it with constant or locally composed text, never upstream text."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Job:
    """State of one build, safe to read from the event loop while a thread updates it."""

    def __init__(self, params: JobParams, clock: Callable[[], float]) -> None:
        self.id = secrets.token_hex(8)
        self.params = params
        self.tracker = Tracker(clock)
        self.state = "queued"
        self.error: str | None = None
        self.created = clock()
        self.finished: float | None = None
        self.build_over = False  # the build thread has ended (set under the manager's lock)
        self._clock = clock
        self._lock = threading.Lock()

    def _end(self, state: str, error: str | None) -> bool:
        with self._lock:
            if self.state in ("done", "error"):
                return False
            self.state, self.error, self.finished = state, error, self._clock()
            return True

    def start(self) -> None:
        with self._lock:
            if self.state == "queued":
                self.state = "running"

    def succeed(self) -> bool:
        return self._end("done", None)

    def fail(self, message: str) -> bool:
        return self._end("error", message)

    def status(self, queue_position: int | None) -> dict:
        stage, fraction = self.tracker.snapshot()
        end = self.finished if self.finished is not None else self._clock()
        done = self.state == "done"
        return {
            "job": self.id,
            "state": self.state,
            "stage": "Done" if done else ("Failed" if self.state == "error" else stage),
            "progress": 1.0 if done else round(fraction, 3),
            "elapsed_s": round(end - self.created, 1),
            "queue_position": queue_position,
            "manifest_url": f"/api/views/{self.params.key}/manifest.json" if done else None,
            "error": self.error,
        }


class JobManager:
    """Starts, deduplicates, queues and times out builds."""

    def __init__(self, cache: ViewCache, build_fn: BuildFn, *, max_builds: int,
                 queue_cap: int, timeout_s: float, ttl_s: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic, max_abandoned: int = 4,
                 exit_when_stuck: bool = False, exit_grace_s: float = 30.0,
                 after_build: Callable[[], None] | None = None,
                 exit_fn: Callable[[int], None] = os._exit) -> None:
        self.max_abandoned, self.exit_when_stuck = max_abandoned, exit_when_stuck
        self.exit_grace_s, self.after_build, self._exit = exit_grace_s, after_build, exit_fn
        self._abandoned: set[str] = set()  # timed-out jobs whose build thread still runs
        self.cache, self.build_fn = cache, build_fn
        self.queue_cap, self.timeout_s, self.ttl_s = queue_cap, timeout_s, ttl_s
        self.clock, self.max_builds = clock, max_builds
        self._slots_busy = 0  # pool threads holding a build, including timed-out ones
        self._pool = ThreadPoolExecutor(max_workers=max_builds, thread_name_prefix="pxs-build")
        self._jobs: dict[str, Job] = {}
        self._active: dict[str, Job] = {}  # cache key -> queued or running job
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self, key: str) -> Job | None:
        with self._lock:
            return self._active.get(key)

    def queue_position(self, job: Job) -> int | None:
        if job.state != "queued":
            return None
        with self._lock:
            queued = [j for j in self._jobs.values() if j.state == "queued"]
        queued.sort(key=lambda j: j.created)
        return next((i + 1 for i, j in enumerate(queued) if j is job), None)

    def counts(self) -> dict[str, int]:
        with self._lock:
            states = [j.state for j in self._jobs.values()]
        return {"running": states.count("running"), "queued": states.count("queued"),
                "abandoned": self.abandoned_count()}

    def abandoned_count(self) -> int:
        with self._lock:
            return len(self._abandoned)

    def healthy(self) -> bool:
        """False when too many timed-out build threads are still stuck."""
        return self.abandoned_count() < self.max_abandoned

    def submit(self, params: JobParams) -> tuple[Job, bool]:
        """The active job for these params, or a new one. Returns (job, created)."""
        with self._lock:
            self._prune()
            existing = self._active.get(params.key)
            if existing is not None:
                return existing, False
            if len(self._abandoned) >= self.max_abandoned:
                raise QueueFull  # stuck threads are piling up; do not add more work
            queued = sum(j.state == "queued" for j in self._jobs.values())
            if queued >= self.queue_cap + max(0, self.max_builds - self._slots_busy):
                raise QueueFull
            job = Job(params, self.clock)
            self._jobs[job.id] = job
            self._active[params.key] = job
        self._pool.submit(self._run, job)
        log.info("job %s queued for view %s", job.id, params.key[:12])
        return job, True

    def _prune(self) -> None:
        cutoff = self.clock() - self.ttl_s
        for jid in [k for k, j in self._jobs.items()
                    if j.finished is not None and j.finished < cutoff]:
            del self._jobs[jid]

    def _release(self, job: Job) -> None:
        with self._lock:
            if self._active.get(job.params.key) is job:
                del self._active[job.params.key]

    def _run(self, job: Job) -> None:
        if job.tracker.cancelled.is_set():
            return
        with self._lock:
            self._slots_busy += 1
        try:
            self._run_slot(job)
        finally:
            with self._lock:
                self._slots_busy -= 1

    def _run_slot(self, job: Job) -> None:
        job.start()
        job.tracker.deadline = self.clock() + self.timeout_s
        work = self.cache.work_dir(job.params.key, job.id)
        thread = threading.Thread(target=self._build, args=(job, work), daemon=True,
                                  name=f"pxs-view-{job.id}")
        thread.start()
        thread.join(self.timeout_s)
        alive = thread.is_alive()
        # The build may also have stopped itself at its deadline (BuildCancelled) just before
        # this join timed out; it then ends without succeeding or failing the job.
        if alive or job.tracker.cancelled.is_set():
            job.tracker.cancelled.set()
            if job.fail(f"Building this view took longer than {self.timeout_s:g} s, so it was "
                        "stopped. The data archives may be slow; try again later."):
                log.warning("job %s timed out after %g s", job.id, self.timeout_s)
            self._release(job)
        if alive:
            self._abandon(job)  # the slot is freed; the thread may linger
        self.cache.discard(work)
        if self.after_build is not None:
            try:
                self.after_build()
            except Exception:
                log.exception("after-build housekeeping failed")

    def _abandon(self, job: Job) -> None:
        with self._lock:
            if job.build_over:  # finished between the join and here
                return
            self._abandoned.add(job.id)
            stuck = len(self._abandoned)
        log.warning("job %s abandoned its build thread (%d abandoned)", job.id, stuck)
        if self.exit_when_stuck and stuck >= self.max_abandoned:
            timer = threading.Timer(self.exit_grace_s, self._exit_if_still_stuck)
            timer.daemon = True
            timer.start()

    def _exit_if_still_stuck(self) -> None:
        if not self.healthy():
            log.error("still at %d abandoned build threads; exiting so the platform restarts "
                      "the service", self.max_abandoned)
            self._exit(1)

    def _build(self, job: Job, work: Path) -> None:
        try:
            manifest = self.build_fn(job.params, work, job.tracker.report)
            if job.tracker.cancelled.is_set():
                return
            degraded = is_degraded(manifest) if isinstance(manifest, dict) else False
            self.cache.commit(job.params.key, work, degraded=degraded)
            job.succeed()
            log.info("job %s done in %.1f s%s", job.id, self.clock() - job.created,
                     " (degraded)" if degraded else "")
        except BuildCancelled:
            log.info("job %s stopped after cancellation", job.id)
        except BuildError as exc:
            log.warning("job %s found no data: %s", job.id, exc)
            job.fail(NO_DATA)
        except AuthoredFailure as exc:
            log.warning("job %s failed: %s", job.id, exc.message)
            job.fail(exc.message)
        except Exception:
            log.exception("job %s failed", job.id)
            job.fail(SERVER_FAULT)
        finally:
            self._release(job)
            with self._lock:
                job.build_over = True
                self._abandoned.discard(job.id)
            if job.tracker.cancelled.is_set():
                self.cache.discard(work)  # an abandoned build cleans up after itself

    def close(self) -> None:
        """Cancel everything and stop accepting work (used at shutdown and in tests)."""
        with self._lock:
            jobs = list(self._jobs.values())
        for j in jobs:
            j.tracker.cancelled.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
