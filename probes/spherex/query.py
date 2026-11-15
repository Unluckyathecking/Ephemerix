"""Check 1: which SPHEREx Level-2 frames cover each target, per collection.

Usage: uv run python probes/spherex/query.py
Writes cache/spherex_frames.json (frame list used by later probes).
"""
import io
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io.votable import parse_single_table
from astropy.time import Time

from targets import TARGETS, coord_at

CACHE = Path(__file__).resolve().parents[2] / "cache"

SIA = "https://irsa.ipac.caltech.edu/SIA"
UA = {"User-Agent": "planet-x-spherex-probe"}
COLLECTIONS = ["spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep", "spherex_qr2"]
IBE_PREFIX = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"
EPOCH_GAP_DAYS = 20.0  # frames closer than this in time belong to one visit/epoch


def sia_frames(collection: str, ra: float, dec: float, radius_deg: float = 0.0005) -> list[dict]:
    """Query IRSA SIA2 for one collection; return a list of frame dicts."""
    params = {"COLLECTION": collection, "POS": f"circle {ra} {dec} {radius_deg}",
              "RESPONSEFORMAT": "VOTABLE"}
    r = requests.get(SIA, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    tab = parse_single_table(io.BytesIO(r.content)).to_table(use_names_over_ids=True)
    if len(tab) == 0:
        return []
    out = []
    for row in tab:
        url = str(row["access_url"])
        cloud = json.loads(str(row["cloud_access"])) if str(row["cloud_access"]) else {}
        out.append({
            "collection": collection,
            "obs_id": str(row["obs_id"]),
            "detector": int(str(row["energy_bandpassname"])[-1]),
            "subtype": str(row["dataproduct_subtype"]),
            "mjd": float(row["t_min"]),
            "em_min_um": float(row["em_min"]) * 1e6,
            "em_max_um": float(row["em_max"]) * 1e6,
            "url": url,
            "s3_key": cloud.get("aws", {}).get("key"),
        })
    return out


def group_epochs(mjds: list[float]) -> list[tuple[float, float, int]]:
    """Cluster sorted MJDs into (start, end, n) groups split at gaps > EPOCH_GAP_DAYS."""
    if not mjds:
        return []
    m = np.sort(np.asarray(mjds))
    cuts = np.where(np.diff(m) > EPOCH_GAP_DAYS)[0] + 1
    return [(float(g[0]), float(g[-1]), len(g)) for g in np.split(m, cuts)]


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd").iso[:10]


def main() -> None:
    all_frames: dict[str, list[dict]] = {}
    jobs = []
    for name in TARGETS:
        c = coord_at(name, Time("2025-11-01"))
        for coll in COLLECTIONS:
            jobs.append((name, coll, c.ra.deg, c.dec.deg))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda j: (j[0], j[1], sia_frames(j[1], j[2], j[3])), jobs))
    print(f"{len(jobs)} SIA queries in {time.time() - t0:.1f}s (6 parallel)")
    for name, coll, frames in res:
        all_frames.setdefault(name, []).extend(frames)

    for name, frames in all_frames.items():
        print(f"\n## {name}  total rows {len(frames)}")
        by_coll = defaultdict(list)
        for f in frames:
            by_coll[f["collection"]].append(f)
        for coll, fs in by_coll.items():
            det = Counter(f["detector"] for f in fs)
            mj = [f["mjd"] for f in fs]
            eps = group_epochs(mj)
            print(f"  {coll:18s} n={len(fs):4d} det={dict(sorted(det.items()))} "
                  f"{iso(min(mj))}..{iso(max(mj))}")
            for a, b, n in eps:
                print(f"      epoch {iso(a)}..{iso(b)}  n={n}")
        ids = defaultdict(set)
        for f in frames:
            ids[f["collection"]].add((f["obs_id"], f["detector"]))
        cols = list(ids)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                ov = ids[a] & ids[b]
                if ov:
                    print(f"  overlap {a} & {b}: {len(ov)} identical obs_id+detector")
    with open(CACHE / "spherex_frames.json", "w") as fh:
        json.dump(all_frames, fh)


if __name__ == "__main__":
    main()
