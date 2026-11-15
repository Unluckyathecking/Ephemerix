"""Frame search: one IRSA SIA2 query and one TAP quality lookup per mission phase.

A circle inside a committed frame list (``framelist``, data/frames/wise/) is answered from
the list, with no IRSA query at all. When TAP fails, NEOWISE frames still get ``qual_frame``
from the NEOWISE source table in s3 (``neoqual``, about 3 s).

SIA2 lists frames and footprints and is fast. TAP adds ``qual_frame`` (and Moon/SAA
distances), lists the 2010 three-band frames (SIA's three-band collection is empty, see
``frames``), and is the slow, sometimes overloaded leg: 10-25 s per phase on a good day, 60 s
timeouts or 502s on a bad one. Neither the SIA rows nor the L1b frame headers carry
``qual_frame`` (the headers have MOONSEP and GCD2SAA but no quality score), so there is no
cheaper source of the same number.

TAP runs beside SIA on daemon threads, holding at most ``IRSA_OPTIONAL_MAX`` of the IRSA
slots so required queries always get one, and is waited for only until ``TAP_BUDGET_S``
after the search started. Whatever answered is used:
- TAP missing for a phase: its SIA frames with unknown quality (the stacker still drops
  frames by their measured noise, ``combine.reject_noisy``); one sentence says so, and the
  view is not degraded for that alone, since every frame was obtained.
- SIA missing for a phase: that phase's TAP rows (a footprint superset) stand in.
- Both missing (and TAP missing for the TAP-only three-band phase): the phase's frames are
  found from the public bucket itself, with no IRSA query (``bucketsearch``: committed scan
  tracks for 2010-2011, the NEOWISE source table for 2013-2024), so an IRSA outage still
  gives every image. Only if that fails too is the phase left out, with a sentence naming
  its years, and ``Frames.partial`` is set so the view is marked degraded and rebuilt soon.
  Only when nothing answered at all does this raise, so
"the archive failed" is never reported as "no frames here". A TAP answer that arrives after
the budget is still cached on disk by ``net.get_text`` for the next build.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace

from pxs.concurrency import IRSA_MAX_CONCURRENT, background, limited
from pxs.wise import framelist, neoqual, net
from pxs.wise.frames import TAP_COLUMNS, Frame, merge, parse_sia, parse_tap
from pxs.wise.phases import PHASES, Phase

log = logging.getLogger(__name__)

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
TAP_URL = "https://irsa.ipac.caltech.edu/TAP/sync"
FRAME_HALF_DIAGONAL_DEG = 0.6  # 1016 px x 2.75"/px / 2 x sqrt(2) = 0.55 deg, plus slack
IRSA_WORKERS = 4
TAP_BUDGET_S = 20.0  # how long a build waits for the quality lookup, from the search start
IRSA_OPTIONAL_MAX = IRSA_MAX_CONCURRENT - 1  # TAP lookups in flight; one slot stays free
# One attempt, read timeout just past the budget: an abandoned lookup frees its IRSA slot
# within about 25 s instead of the default 41 s worst case.
TAP_TIMEOUT_S = (5.0, TAP_BUDGET_S)
TAP_RETRIES = 0
# IRSA's proxy answers 502 in bursts: three SIA attempts, 1 s and 2 s apart. Worst case
# when SIA hangs instead: 3 x (5 s + 60 s) + 3 s = 198 s, inside the 480 s build limit.
SIA_RETRIES = 2

NO_QUALITY = ("WISE frame-quality scores did not arrive from IRSA in time, so some WISE "
              "frames were chosen by coverage alone; frames with unusual noise are still left "
              "out.")
TAP_ONLY = {"3band"}  # phases whose frames only the TAP lookup lists (SIA's collection is empty)
PHASE_YEARS = {"allsky": "2010 (cryogenic)", "3band": "2010 (three-band)",
               "postcryo": "2010-2011 (post-cryogenic)", "neowiser": "2013-2024 (NEOWISE)"}

_tap_slots = limited(IRSA_OPTIONAL_MAX)


class Frames(list):
    """The frames found (a plain list to callers), plus ``warnings`` (sentences for the user)
    and ``partial`` (some frames could not be listed)."""

    def __init__(self, frames: Iterable[Frame] = (), warnings: tuple[str, ...] = (),
                 partial: bool = False) -> None:
        super().__init__(frames)
        self.warnings, self.partial = warnings, partial


def _sia(p: Phase, ra: float, dec: float, radius_deg: float) -> list[Frame]:
    params = {"COLLECTION": p.sia_collection, "POS": f"CIRCLE {ra:.7f} {dec:.7f} {radius_deg:.6f}",
              "RESPONSEFORMAT": "CSV"}
    return parse_sia(net.get_text(SIA_URL, params, retries=SIA_RETRIES))


def _tap_params(p: Phase, ra: float, dec: float, radius_deg: float) -> dict[str, str]:
    cone = radius_deg + FRAME_HALF_DIAGONAL_DEG
    query = (f"SELECT {TAP_COLUMNS} FROM {p.tap_table} WHERE band IN (1, 2) AND "
             f"CONTAINS(POINT('ICRS', crval1, crval2), "
             f"CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {cone:.6f}))=1")
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}


def _with_cached_tap(frames: list[Frame], missing: list[str], ra: float, dec: float,
                     radius_deg: float) -> tuple[list[Frame], list[str]]:
    """A listed result plus any TAP answer already in the on-disk cache (never the network),
    for phases the list lacks or could not score: it adds scores and TAP-only frames."""
    tap: list[Frame] = []
    for p in PHASES:
        if p.name not in missing and all(f.qual_frame is not None
                                         for f in frames if f.phase == p.name):
            continue
        try:
            text = net.cached_text(TAP_URL, _tap_params(p, ra, dec, radius_deg))
            if text is not None:
                tap += parse_tap(text, p.name)
                missing = [m for m in missing if m != p.name]
        except Exception as exc:  # noqa: BLE001 - a bad cache entry only loses the extra
            log.warning("cached WISE quality lookup of %s unusable: %s", p.name, exc)
    return (merge(frames, tap) if tap else frames), missing


def _tap(p: Phase, ra: float, dec: float, radius_deg: float) -> list[Frame]:
    """Frames whose centre lies within the frame half-diagonal of the search circle (a superset;
    a column-valued CIRCLE is rejected by IRSA, so this is a centre-distance cone)."""
    params = _tap_params(p, ra, dec, radius_deg)
    text = net.cached_text(TAP_URL, params)  # a cached answer never waits for a slot
    if text is None:
        with _tap_slots():
            text = net.get_text(TAP_URL, params, post=True, timeout=TAP_TIMEOUT_S,
                                retries=TAP_RETRIES)
    return parse_tap(text, p.name)


def _answer(fut: Future, deadline: float | None, what: str) -> list[Frame] | None:
    """The future's frames, or None if it failed or missed ``deadline`` (monotonic)."""
    try:
        wait = None if deadline is None else max(0.0, deadline - time.monotonic())
        return fut.result(timeout=wait)
    except FutureTimeout:
        log.warning("%s not answered within %g s", what, TAP_BUDGET_S)
    except Exception as exc:  # noqa: BLE001 - judged per phase by the caller
        log.warning("%s failed (%s: %s)", what, type(exc).__name__, exc)
    return None


def _with_neowise_quality(frames: list[Frame], ra: float, dec: float,
                          radius_deg: float) -> list[Frame]:
    """NEOWISE frames with scores from the public source table (``neoqual``)."""
    scores = neoqual.quality(ra, dec, radius_deg)
    out = []
    for f in frames:
        q = scores.get((f.scan_id, f.frame_num))
        out.append(f if q is None else replace(f, qual_frame=q[0], saa_sep_deg=q[1]))
    return out


def _from_bucket(phases: list[Phase], ra: float, dec: float,
                 radius_deg: float) -> dict[str, list[Frame]]:
    """Frames of the phases IRSA did not list, found from the bucket alone, by phase name;
    a phase the bucket route could not list either is absent."""
    from pxs.wise import bucketsearch  # here: bucketlist imports this module's constant

    if not phases:
        return {}
    with ThreadPoolExecutor(len(phases)) as ex:
        got = list(ex.map(lambda p: bucketsearch.phase_frames(p.name, ra, dec, radius_deg),
                          phases))
    return {p.name: r for p, r in zip(phases, got) if r is not None}


def search_frames(ra: float, dec: float, radius_deg: float,
                  workers: int = IRSA_WORKERS) -> Frames:
    """All W1/W2 frames near a circle, with quality where TAP knows it, sorted by MJD.

    The list is a superset: TAP-only frames may not cover the circle, so callers must test
    each footprint. Angles in degrees. See the module docstring for what happens when a
    query fails; raises RuntimeError only when no query at all answered.
    """
    listed = framelist.lookup(ra, dec, radius_deg)
    if listed is not None:  # a committed list covers this circle: no IRSA query at all
        frames, missing = _with_cached_tap(*listed, ra, dec, radius_deg)
        return Frames(frames, framelist.warnings(frames, missing), partial=bool(missing))
    deadline = time.monotonic() + TAP_BUDGET_S
    with ThreadPoolExecutor(workers) as ex:  # SIA first, so it is not queued behind TAP
        sia_jobs = [ex.submit(_sia, p, ra, dec, radius_deg) for p in PHASES]
        tap_jobs = [background(_tap, p, ra, dec, radius_deg) for p in PHASES]
        sias = [_answer(f, None, f"WISE SIA search of {p.name}") for f, p in zip(sia_jobs, PHASES)]
    taps = [_answer(f, deadline, f"WISE quality lookup of {p.name}")
            for f, p in zip(tap_jobs, PHASES)]
    unlisted = [p for p, a, b in zip(PHASES, sias, taps)
                if b is None and (a is None or p.name in TAP_ONLY)]
    bucket = _from_bucket(unlisted, ra, dec, radius_deg)
    if all(r is None for r in sias + taps) and not bucket:
        raise RuntimeError("every WISE frame search failed (SIA, TAP and the bucket)")
    sias = [_with_neowise_quality(a, ra, dec, radius_deg)
            if p.name == "neowiser" and a and b is None else a
            for p, a, b in zip(PHASES, sias, taps)]
    lost = [p for p in unlisted if p.name not in bucket]
    taps = [bucket.get(p.name, b) for p, b in zip(PHASES, taps)]  # bucket rows are TAP-like
    warnings = []
    if any(b is None and a and p.name not in TAP_ONLY and any(f.qual_frame is None for f in a)
           for p, a, b in zip(PHASES, sias, taps)) \
            or any(f.qual_frame is None for r in bucket.values() for f in r):
        warnings.append(NO_QUALITY)
    if lost:
        years = ", ".join(PHASE_YEARS[p.name] for p in lost)
        warnings.append(f"The IRSA search for WISE frames from {years} failed, so those "
                        "frames are missing.")
    sia = [f for r in sias if r for f in r]
    tap = [f for r in taps if r for f in r]
    frames = merge(sia, tap)
    log.info("search %.5f %.5f r=%.4f: %d SIA + %d TAP rows -> %d frames (%d without quality)",
             ra, dec, radius_deg, len(sia), len(tap), len(frames),
             sum(f.qual_frame is None for f in frames))
    return Frames(frames, tuple(warnings), partial=bool(lost))
