"""Registration of each stacked frame against Gaia DR3: field-star centroids minus their
Gaia positions propagated to the frame epoch, per frame and pooled per band.

    uv run python probes/astro/registration.py <slug> [...] [--json out.json]

Stars: Gaia G 9-18, no Gaia source within ISOLATION_ARCSEC less than
NEIGHBOUR_DMAG fainter, at least 30 arcsec from the
target and 15 px from the edge, centroid S/N >= 10, unsaturated. Offsets are (east, north)
in arcsec. Reads the stacks pickled by dump_stacks.py (our own files, so unpickling is safe).
Written with Claude Code.
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np

from pxs import centroid
from pxs.astrometry import decimal_year, propagate
from pxs.build import REPO, _ids, _position_px

ISOLATION_ARCSEC = 12.0
NEIGHBOUR_DMAG = 2.5  # neighbours fainter than this are ignored
G_RANGE = (9.0, 18.0)
log = logging.getLogger("registration")


def stars_at(gaia: list[dict], grid, year: float) -> list[tuple[float, float, float]]:
    out = []
    for s in gaia:
        ra, dec = propagate(s["ra"], s["dec"], s["epoch"], s.get("pmra_masyr") or 0.0,
                            s.get("pmdec_masyr") or 0.0, year)
        x, y = grid.sky_to_px(ra, dec)
        out.append((float(x), float(y), s.get("g_mag") or 99.0))
    return out


def usable(stars, target_px, size, scale) -> list[int]:
    a = np.array([(x, y) for x, y, _ in stars])
    keep = []
    for i, (x, y, g) in enumerate(stars):
        if not G_RANGE[0] <= g <= G_RANGE[1] or not (15 < x < size - 15 and 15 < y < size - 15):
            continue
        if np.hypot(x - target_px[0], y - target_px[1]) * scale < 30.0:
            continue
        d = np.hypot(a[:, 0] - x, a[:, 1] - y) * scale
        brighter = np.array([gg for _, _, gg in stars]) < g + NEIGHBOUR_DMAG
        if np.sum((d < ISOLATION_ARCSEC) & brighter) > 1:
            continue
        keep.append(i)
    return keep


def frame_offsets(st, grid, gaia, target_px) -> list[tuple[float, float]]:
    scale = grid.pixscale_arcsec
    stars = stars_at(gaia, grid, float(decimal_year(st.mjd)))
    out = []
    for i in usable(stars, target_px, grid.size_px, scale):
        x, y, _ = stars[i]
        c, notes = centroid.detect(st, (x, y), scale, 3.0)
        sat = st.saturated_mask
        if c is None or c.snr < 10 or (sat is not None and sat[int(c.y), int(c.x)]):
            continue
        out.append((-(c.x - x) * scale, -(c.y - y) * scale))
    return out


def run(slug: str) -> dict:
    d = pickle.loads((REPO / "cache" / "astro" / f"{slug}.pkl").read_bytes())
    t, grid = d["target"], d["grid"]
    frames = []
    for fid, (band, st) in zip(_ids(d["stacks"]), d["stacks"]):
        off = frame_offsets(st, grid, d["gaia"], _position_px(t, grid, st.mjd))
        a = np.array(off).reshape(-1, 2)
        frames.append({"id": fid, "band": band, "mjd": st.mjd, "n": len(a),
                       "median": np.median(a, 0).round(3).tolist() if len(a) else None,
                       "star_rms": a.std(0).round(3).tolist() if len(a) > 1 else None})
    return {"slug": slug, "frames": frames}


def summary(results: list[dict], min_n: int = 3) -> dict:
    by: dict[str, list] = {}
    for r in results:
        for f in r["frames"]:
            if f["n"] >= min_n:
                by.setdefault(f["band"], []).append((r["slug"], f["median"], f["star_rms"], f["n"]))
    out = {}
    for band, rows in sorted(by.items()):
        med = np.array([m for _, m, _, _ in rows])
        rms = np.array([s for _, _, s, _ in rows])
        out[band] = {"frames": len(rows), "mean_offset_en": med.mean(0).round(3).tolist(),
                     "frame_scatter_en": med.std(0).round(3).tolist(),
                     "median_star_rms_en": np.median(rms, 0).round(3).tolist(),
                     "per_field_mean_en": {s: np.mean([m for sl, m, _, _ in rows if sl == s], 0)
                                           .round(3).tolist() for s in {r[0] for r in rows}}}
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        out = Path(args[args.index("--json") + 1])
        args = args[:args.index("--json")]
    res = [run(a) for a in args]
    summ = summary(res)
    for band, v in summ.items():
        print(f"{band:7s} frames {v['frames']:3d} mean (E,N) {v['mean_offset_en']} frame scatter "
              f"{v['frame_scatter_en']} star rms {v['median_star_rms_en']}")
        for slug, m in sorted(v["per_field_mean_en"].items()):
            print(f"         {slug:18s} {m}")
    if out:
        out.write_text(json.dumps({"summary": summ, "targets": res}, indent=1))
