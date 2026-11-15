"""Per-point look at a few control-track false detections (diagnostic; not part of the site).

    modal run tools/solarsystem_validation/probe_hits.py

For each (body, variant, pass start MJD) it reruns one pass exactly as the campaign did
and returns every point of the pass and of its background control: time, detector,
wavelength, flux, error, track position and the 8 empty-position fluxes of the same frame.
Written with Claude Code.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

try:  # local `modal run` puts this directory on the path; the container has /app/tools
    from modal_run import CPU, INDEX_MOUNT, app, index_volume
except ImportError:
    from solarsystem_validation.modal_run import CPU, INDEX_MOUNT, app, index_volume

PROBES: list[tuple[str, str, float]] = [
    # two bands at S/N >= 5 on a control track
    ("55637", "off_ra", 0), ("202421", "off_ra", 0), ("208996", "off_ra", 0),
    ("523692", "off_ra", 0), ("90377", "off_dec", 0), ("1404", "off_dec", 0),
    # one band only
    ("55636", "off_dec", 0), ("574372", "off_dec", 0), ("180", "off_dec", 0),
    ("5335", "off_ra", 0),
    # quiet comparison
    ("136108", "off_ra", 0),
]


def _pt(p, eph=None) -> dict:
    d = {"mjd": p.mjd, "det": p.detector, "wl": p.wl_um, "f": p.flux_mjy * 1e3,
         "e": p.err_mjy * 1e3, "flag": p.flagged, "reason": p.reason,
         "empty": [x * 1e3 for x in p.empty_mjy]}
    if eph is not None:
        d |= {"ra": eph.ra, "dec": eph.dec}
    return d


@app.function(cpu=CPU, memory=8192, timeout=1800, region="us-east",
              volumes={INDEX_MOUNT: index_volume.read_only()},
              env={"PXS_SPHEREX_INDEX": INDEX_MOUNT, "PXS_CACHE": "/tmp/pxs-cache",
                   "PXS_PROCESSES": str(int(CPU))})
def probe(pdes: str, variant: str, want: list[float], mjd_stop: float) -> dict:
    import math

    from pxs.solarsystem.bodies import resolve
    from pxs.solarsystem.pipeline import analyse_pass
    from pxs.solarsystem.track import find_visits, passes_of
    from solarsystem_validation.measure import OFFSETS, offset_visits

    t0 = time.time()
    track = find_visits(resolve(pdes).horizons, mjd_stop)
    visits = offset_visits(track.visits, *OFFSETS[variant])
    out = []
    for pas, vs in passes_of(visits):
        if want and not any(abs(pas.mjd_start - w) < 0.01 for w in want):
            continue
        res = analyse_pass({}, pas, vs, with_stacks=False, with_control=True)
        if res is None:
            continue
        out.append({"date_start": pas.mjd_start,
                    "bands": [b.to_dict() for b in res.corrected],
                    "points": [_pt(m.point, m.visit.eph) for m in res.measured],
                    "control": [_pt(p) for p in res.control.points] if res.control else [],
                    "best": res.best.band if res.best else None,
                    "best_snr": res.best.snr if res.best and math.isfinite(res.best.snr)
                    else None})
    return {"pdes": pdes, "variant": variant, "passes": out, "wall_s": time.time() - t0}


@app.local_entrypoint()
def probe_main(records: str, out: str = "probe.json") -> None:
    jobs = []
    for pdes, variant, _ in PROBES:
        rec = json.loads((Path(records) / pdes / f"{variant}.json").read_text())
        want = [p["date_start"] for p in rec["passes"] if p["detected"]] or \
            [p["date_start"] for p in rec["passes"][:1]]
        jobs.append((pdes, variant, want, rec["mjd_stop"]))
    res = list(probe.starmap(jobs, return_exceptions=True))
    good = [r for r in res if isinstance(r, dict)]
    for r in res:
        if not isinstance(r, dict):
            print("FAILED", type(r).__name__, str(r)[:200])
    print("container s:", round(sum(r["wall_s"] for r in good)))
    Path(out).write_text(json.dumps(good, allow_nan=True))
