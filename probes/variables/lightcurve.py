"""Per-exposure forced PSF photometry of a target and nearby comparison stars, all collections.

Uses pxs.spherex (find_frames, read_many, measure, error_scale) unchanged. Comparison stars
are measured in the same stamps with measure(stamp, dx, dy), so they share every frame,
wavelength and calibration with the target. Results cached as JSON under cache/variables/lc/.

Usage (from repo root): uv run python probes/variables/lightcurve.py <slug>
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

from pxs.spherex import config
from pxs.spherex.net import BlockStore
from pxs.spherex.photometry import error_scale, measure
from pxs.spherex.query import find_frames
from pxs.spherex.stamps import read_many

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "cache" / "variables" / "lc"
STORE_ROOT = ROOT / "cache" / "variables" / "s3"
ALL = config.COLLECTIONS + config.DEEP_COLLECTIONS
HALF = 15  # 31 px stamp, as in pxs.spherex
COMP_HALF = 12  # comparison stars get their own 25 px stamp (headers are already cached, so cheap)


def subsample(frames: list, n_max: int) -> list:
    """Evenly spaced (in time order) subset of at most n_max frames."""
    if len(frames) <= n_max:
        return frames
    idx = np.unique(np.linspace(0, len(frames) - 1, n_max).round().astype(int))
    return [frames[i] for i in idx]


def run(slug: str, ra: float, dec: float, comps: list[tuple[str, float, float]],
        n_max: int = 400, collections: tuple[str, ...] = ALL) -> dict:
    path = OUT / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text())
    frames = find_frames(ra, dec, collections=collections)
    by_coll = {c: sum(f.collection == c for f in frames) for c in collections}
    use = subsample(frames, n_max)
    logging.info("%s: %d frames %s, reading %d", slug, len(frames), by_coll, len(use))
    store = BlockStore(root=STORE_ROOT)
    batch = read_many([(f, ra, dec) for f in use], HALF, with_psf=True, store=store, workers=8)
    stamps = batch.stamps
    comp_ph = {}
    for name, cra, cdec in comps:
        cb = read_many([(f, cra, cdec) for f, _ in stamps], COMP_HALF, with_psf=True, store=store, workers=8)
        sc = {}
        for det in range(1, 7):
            sub = [s for _, s in cb.stamps if s.detector == det]
            sc[det] = error_scale(sub, min_samples=40) if len(sub) >= 5 else config.ERROR_SCALE
        for f, s in cb.stamps:
            m = measure(s)
            comp_ph[(name, f.s3_key)] = [m.flux_mjy, m.err_mjy * sc[s.detector], m.reason, s.wave_um]
    scale = {}
    for det in range(1, 7):
        sub = [s for _, s in stamps if s.detector == det]
        scale[det] = error_scale(sub, min_samples=40) if len(sub) >= 5 else config.ERROR_SCALE
    rows = []
    for f, s in stamps:
        m = measure(s)
        row = {"mjd": s.mjd, "det": s.detector, "wl": s.wave_um, "bw": s.band_um,
               "coll": f.collection, "flux": m.flux_mjy, "err": m.err_mjy * scale[s.detector],
               "reason": m.reason, "comps": {}}
        for name, _, _ in comps:
            if (name, f.s3_key) in comp_ph:
                row["comps"][name] = comp_ph[(name, f.s3_key)]
        rows.append(row)
    res = {"slug": slug, "ra": ra, "dec": dec, "n_frames_total": len(frames),
           "frames_by_collection": by_coll, "n_read": len(use), "n_failed": batch.n_failed,
           "error_scale": scale, "comps": comps, "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, default=float))
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    spec = json.loads((OUT.parent / "lc_specs.json").read_text())[sys.argv[1]]
    r = run(sys.argv[1], spec["ra"], spec["dec"], [tuple(c) for c in spec["comps"]],
            spec.get("n_max", 400), tuple(spec.get("collections", ALL)))
    ok = [x for x in r["rows"] if not x["reason"]]
    print(sys.argv[1], r["frames_by_collection"], "read", r["n_read"], "measured", len(ok))
