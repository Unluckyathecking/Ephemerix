"""Run one sample body through the Solar System pipeline: the real track and its controls.

One record per (body, variant) is handed to `write` as soon as it is finished, so a later
failure never loses an earlier result. Variants: "real" (the body's own track) and the
negative controls of measure.OFFSETS (the same frames with the track shifted; no body).
Each pass is analysed exactly as `pxs.solarsystem.pipeline.analyse_pass` does for the
site, with its background control, but without image stacks (only the body-centred stack
of the best band is built, for the position gate).

Written with Claude Code.
"""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable, Iterable

from pxs.solarsystem.bodies import resolve
from pxs.solarsystem.pipeline import MIN_PASS_FRAMES, analyse_pass
from pxs.solarsystem.track import Track, find_visits, passes_of

from .measure import OFFSETS, classify_error, offset_visits, pass_record, plain

log = logging.getLogger(__name__)

VARIANTS: tuple[str, ...] = ("real", *OFFSETS)


def track_summary(track: Track) -> dict:
    return {"n_visits": len(track.visits), "n_days": len(track.daily),
            "n_cones": track.n_cones, "failed_cones": track.failed_cones,
            "n_index_days": track.n_index_days,
            "unsearched_after_mjd": track.unsearched_after_mjd}


def measure_variant(track: Track, variant: str) -> dict:
    """Pass records (analysed passes) and skipped passes for one variant of the track."""
    visits = list(track.visits) if variant == "real" else offset_visits(
        track.visits, *OFFSETS[variant])
    timings: dict[str, float] = {}
    passes, skipped = [], []
    for pas, vs in passes_of(visits):
        res = analyse_pass(timings, pas, vs, with_stacks=False, with_control=True)
        if res is None:
            skipped.append({"date_start": pas.mjd_start, "date_end": pas.mjd_end,
                            "n_frames": len(vs), "min_frames": MIN_PASS_FRAMES})
        else:
            passes.append(pass_record(res))
    return {"passes": passes, "skipped": skipped, "timings": timings}


def _error(e: BaseException, stage: str) -> dict:
    kind = classify_error(e)
    if stage == "track" and kind == "network":  # the track stage only talks to Horizons
        kind = "horizons"
    return {"kind": kind, "stage": stage, "type": type(e).__name__, "message": str(e)[:500],
            "traceback": traceback.format_exc()[-4000:]}


def run(body: dict, mjd_stop: float, variants: Iterable[str], provenance: dict,
        write: Callable[[str, dict], None]) -> dict:
    """Measure the given variants of one body, writing each record as it is finished.

    Returns a small status dict {variant: status}. Never raises for a body's own failure.
    """
    t0 = time.perf_counter()
    base = {"body": body, "provenance": provenance, "mjd_stop": mjd_stop}
    pending = list(variants)
    status: dict[str, str] = {}

    def emit(variant: str, rec: dict) -> None:
        rec = plain({**base, "variant": variant, **rec,
                     "wall_s": round(time.perf_counter() - t0, 1)})
        write(variant, rec)
        status[variant] = rec["status"]

    try:
        track = find_visits(resolve(body["pdes"]).horizons, mjd_stop)
    except Exception as e:
        log.exception("track for %s failed", body["pdes"])
        err = _error(e, "track")
        for v in pending:
            emit(v, {"status": "error", "error": err, "track": None, "passes": [],
                     "skipped": []})
        return status
    summary = track_summary(track)
    for v in pending:
        t1 = time.perf_counter()
        try:
            out = measure_variant(track, v)
            emit(v, {"status": "ok", "error": None, "track": summary, **out,
                     "variant_s": round(time.perf_counter() - t1, 1)})
        except Exception as e:
            log.exception("%s %s failed", body["pdes"], v)
            emit(v, {"status": "error", "error": _error(e, "measure"), "track": summary,
                     "passes": [], "skipped": []})
    return status
