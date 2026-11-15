"""The build function for a Solar System body view: `pxs.solarsystem` with a time budget.

The job manager stops a build at its timeout and keeps nothing, so the body pipeline gets
its own, earlier deadline: passes are measured while time allows, and a view with the
passes done (marked degraded, with a warning) is written instead of failing. Every failure
is one of the fixed sentences below, raised as AuthoredFailure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pxs.api.bodies import BodyParams
from pxs.api.jobs import AuthoredFailure, BuildFn
from pxs.api.progress import Report
from pxs.solarsystem import bodymanifest
from pxs.solarsystem.pipeline import MARGINAL, BodyRun, run_body
from pxs.spherex.localindex import ENV_DIR

log = logging.getLogger("pxs.api.bodyrunner")

RENDER_MARGIN_S = 60.0  # kept back from the job timeout for drawing and writing the view
MIN_BUDGET_SHARE = 0.5

HORIZONS_FAILED = ("JPL Horizons did not answer, so the body's positions could not be "
                   "worked out. Try again later.")
NO_EXPOSURE = "No SPHEREx exposure covers this body yet."
NOT_DETECTED = ("SPHEREx covered this body in {n} pass{es} but did not detect it in any of "
                "them (a detection needs S/N 5 in two detector bands), so there is no view "
                "to show.")
MARGINAL_ONLY = ("SPHEREx covered this body in {n} pass{es}. In {which} one detector band "
                 "reached S/N 5 but no second band did. On empty sky beside known bodies that "
                 "happens in about 6 passes in 100, so it is consistent with noise in this "
                 "field and is not a detection. There is no view to show.")
OUT_OF_TIME = ("Finding this body's SPHEREx exposures took the whole time allowed, so no "
               "pass could be measured. Try again later.")

RunFn = Callable[..., BodyRun]
RenderFn = Callable[[BodyRun, Path], dict]

_tag_lock = threading.Lock()
_tag_cache: dict[tuple[str, int, int], str] = {}


def index_tag() -> str:
    """Identifies the SPHEREx frame index in use (hash of its manifest), or "none"."""
    root = os.environ.get(ENV_DIR, "").strip()
    if not root:
        return "none"
    path = Path(root) / "manifest.json"
    try:
        st = path.stat()
        stamp = (str(path), st.st_mtime_ns, st.st_size)
        with _tag_lock:
            if stamp not in _tag_cache:
                _tag_cache[stamp] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            return _tag_cache[stamp]
    except OSError:
        log.warning("SPHEREx index manifest unreadable; body views keyed without it")
        return "none"


def _check(run: BodyRun) -> None:
    """Raise the authored failure for a run that has nothing to show."""
    if run.track is None:
        raise AuthoredFailure(HORIZONS_FAILED)
    if not run.passes:
        raise AuthoredFailure(OUT_OF_TIME if run.stopped_early else NO_EXPOSURE)
    if not any(p.detected for p in run.passes):
        n, es = len(run.passes), "" if len(run.passes) == 1 else "es"
        k = sum(p.outcome == MARGINAL for p in run.passes)
        which = "that pass" if n == 1 else f"{k} of them"
        raise AuthoredFailure(MARGINAL_ONLY.format(n=n, es=es, which=which) if k
                              else NOT_DETECTED.format(n=n, es=es))


def make_body_builder(timeout_s: float, run: RunFn = run_body,
                      render: RenderFn = bodymanifest.build) -> BuildFn:
    """A BuildFn for BodyParams that finishes within `timeout_s` when the archives allow."""
    budget = max(timeout_s - RENDER_MARGIN_S, timeout_s * MIN_BUDGET_SHARE)

    def build(params: BodyParams, out_dir: Path, report: Report) -> dict:
        result = run(params.body(), progress=report, deadline=time.monotonic() + budget)
        _check(result)
        report("Drawing the images and writing the view", 0.96)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = render(result, out_dir)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, allow_nan=False))
        return manifest

    return build
