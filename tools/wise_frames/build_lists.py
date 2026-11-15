"""Write data/frames/wise/<slug>.json: every W1/W2 frame near a gallery target, so gallery
builds need no IRSA search (see pxs.wise.framelist).

    PYTHONPATH=tools python -m wise_frames.build_lists [slug ...] [--out data/frames/wise]

Per target, over the circle the build will search (the 2010-2025 path plus PAD_DEG):
- allsky, postcryo, neowiser: IRSA SIA2, retried; a phase that still fails is "missing".
- neowiser scores: the NEOWISE-R source table in s3 (pxs.wise.neoqual), not IRSA TAP.
- 2010 scores and 3band frames: one short IRSA TAP attempt per phase. If TAP fails, 3band
  (SIA's collection is empty) is listed from the bucket's scan tracks
  (wise_frames.threeband, no score); if that fails too, it is "none" when the target's
  NEOWISE visit dates, moved back to 2010, miss the three-band window (wise_frames.timing),
  otherwise "missing".
Needs IRSA SIA to answer; about 10 s and 3 MB per target. Network results are cached under
PXS_WISE_CACHE as for builds.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from pxs.target import Target, load_targets
from pxs.wise import framelist
from pxs.wise.frames import Frame, merge
from pxs.wise.phases import PHASES, phase
from pxs.wise.search import _sia, _tap, _with_neowise_quality
from pxs.wise.visits import DEFAULT_RADIUS_DEG, _search_radius, group_visits, path_from_motion
from wise_frames import threeband, timing

log = logging.getLogger("wise_frames")

REPO = Path(__file__).resolve().parents[2]
PAD_DEG = 0.01  # list a wider circle than the build asks for, so small target edits still hit
SIA_ATTEMPTS = 4
SIA_HOW = "IRSA SIA2"
NEO_HOW = (f"{SIA_HOW}; qual_frame and saa_sep from the NEOWISE-R single-exposure source "
           "table (s3://nasa-irsa-wise, p1bs_psd)")


def search_circle(t: Target) -> tuple[float, float, float]:
    path = (path_from_motion(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr)
            if t.has_pm else None)
    return t.ra, t.dec, _search_radius(t.ra, t.dec, DEFAULT_RADIUS_DEG, path) + PAD_DEG


def _sia_retried(name: str, ra: float, dec: float, r: float) -> list[Frame] | None:
    for attempt in range(SIA_ATTEMPTS):
        try:
            return _sia(phase(name), ra, dec, r)
        except Exception as exc:  # noqa: BLE001 - retried, then recorded as missing
            log.warning("SIA %s attempt %d failed: %s", name, attempt + 1, exc)
            time.sleep(5 * (attempt + 1))
    return None


def _tap_once(name: str, ra: float, dec: float, r: float) -> list[Frame] | None:
    """One short IRSA TAP attempt (scores for 2010 frames, and the only 3-band listing)."""
    try:
        return _tap(phase(name), ra, dec, r)
    except Exception as exc:  # noqa: BLE001 - TAP is optional here
        log.warning("TAP %s failed: %s", name, exc)
        return None


def _visits(frames: list[Frame]) -> list[timing.Interval]:
    return [(g[0].mjd, g[-1].mjd) for g in group_visits(frames)]


def threeband_status(neo: list[Frame] | None, old: list[Frame]) -> dict:
    if not neo:
        return {"status": "missing", "how": "no NEOWISE visits to time the 2010 visits by"}
    nv, seen = _visits(neo), _visits(old)
    off = timing.unmatched(nv, seen)
    if off:
        return {"status": "missing", "how": f"timing check failed: predicted 2010 visits {off} "
                "have no listed frames"}
    hit = timing.threeband_visit(nv)
    if hit is not None:
        return {"status": "missing", "how": "a 2010 visit predicted at MJD "
                f"{hit[0]:.0f}-{hit[1]:.0f} falls in the three-band window, and only IRSA TAP "
                "lists that phase"}
    pred = ", ".join(f"{a:.0f}-{b:.0f}" for a, b in timing.predicted_2010(nv))
    return {"status": "none", "how": f"timing: 2010 visits predicted from {len(nv)} NEOWISE "
            f"visits at MJD {pred} miss the three-band window "
            f"{timing.THREEBAND_MJD[0]:.0f}-{timing.THREEBAND_MJD[1]:.0f} by more than "
            f"{timing.MARGIN_D:.0f} d, and match the SIA-listed 2010 visits"}


def _threeband(tap: list[Frame] | None, ra: float, dec: float, r: float,
               neo: list[Frame] | None, old: list[Frame]) -> tuple[list[Frame] | None, dict]:
    """The three-band phase: IRSA TAP if it answered, else the bucket's scan tracks
    (wise_frames.threeband), else the timing rule."""
    if tap is not None:
        return tap, {"status": "complete" if tap else "none", "how": "IRSA TAP",
                     "frames": len(tap)}
    frames = threeband.bucket_frames(ra, dec, r)
    if frames is not None:
        return frames, {"status": "complete" if frames else "none", "how": threeband.HOW,
                        "frames": len(frames)}
    return None, threeband_status(neo, old)


def build(t: Target) -> dict:
    ra, dec, r = search_circle(t)
    found = {p.name: _sia_retried(p.name, ra, dec, r) for p in PHASES if p.name != "3band"}
    if found["neowiser"]:
        found["neowiser"] = _with_neowise_quality(found["neowiser"], ra, dec, r)
    tap = {n: _tap_once(n, ra, dec, r) for n in ("allsky", "3band", "postcryo")}
    for n in ("allsky", "postcryo"):
        if found[n] and tap[n]:
            found[n] = merge(found[n], tap[n])  # adds scores, and TAP-only frames (a superset)
    phases = {}
    for name, frames in found.items():
        how = NEO_HOW if name == "neowiser" else SIA_HOW + (" + IRSA TAP" if tap.get(name) else "")
        status = "missing" if frames is None else "complete" if frames else "none"
        phases[name] = {"status": status, "how": how, "frames": len(frames or [])}
    old = (found["allsky"] or []) + (found["postcryo"] or [])
    found["3band"], phases["3band"] = _threeband(tap["3band"], ra, dec, r, found["neowiser"], old)
    frames = sorted((f for fs in found.values() for f in fs or []), key=lambda f: (f.mjd, f.key))
    return {"version": framelist.VERSION, "slug": t.slug, "ra": ra, "dec": dec, "radius_deg": r,
            "made": datetime.now(UTC).strftime("%Y-%m-%d"),
            "phases": {p.name: phases[p.name] for p in PHASES},
            "frames": [framelist.to_row(f) for f in frames]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slugs", nargs="*", help="targets (default: all)")
    ap.add_argument("--targets", type=Path, default=REPO / "data" / "targets.json")
    ap.add_argument("--out", type=Path, default=framelist.DEFAULT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    for t in load_targets(args.targets):
        if args.slugs and t.slug not in args.slugs:
            continue
        start = time.monotonic()
        doc = build(t)
        (args.out / f"{t.slug}.json").write_text(json.dumps(doc, separators=(",", ":")) + "\n")
        summary = {k: (v["status"], v.get("frames")) for k, v in doc["phases"].items()}
        unscored = sum(r[5] is None for r in doc["frames"] if r[0] == "neowiser")
        log.info("%s: %d frames in %.0f s, %s, %d NEOWISE frames unscored", t.slug,
                 len(doc["frames"]), time.monotonic() - start, summary, unscored)


if __name__ == "__main__":
    main()

