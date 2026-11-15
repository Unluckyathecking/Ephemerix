"""Probe: before/after table for the bright-star fixes (eval_bright_modal.py outputs).

    uv run python probes/movers/eval_bright_table.py static halo static_halo
"Before" is the 14 Nov campaign (cache/movers/campaign/units, runs 00-03); each variant is
cache/movers/fixruns/<variant>/. Injection seeds are fixed per (field, run), so recovery is
compared source by source: lost = recovered before and not after, gained the reverse.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

FIELDS = ("BarnardsStar", "WISE0855", "Haumea", "B6")
RUNS = 4
BINS = (0.02, 0.05, 0.1, 0.2, 0.4)  # mJy at 1 um


def load(dirpath: Path, field: str) -> dict | None:
    base = dirpath / f"{field}__base.json"
    if not base.exists():
        return None
    meta = json.loads(base.read_text())
    flux, rec, rate = [], [], []
    for r in range(RUNS):
        p = dirpath / f"{field}__run{r:02d}.npz"
        if not p.exists():
            return None
        z = np.load(p)
        flux.append(z["inj_flux"])
        rec.append(z["inj_rec"])
        rate.append(z["inj_rate"])
    return {"meta": meta, "flux": np.concatenate(flux), "rec": np.concatenate(rec),
            "rate": np.concatenate(rate)}


def cells(d: dict) -> list[str]:
    out = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        k = (d["flux"] >= lo) & (d["flux"] < hi)
        out.append(f"{int(d['rec'][k].sum())}/{int(k.sum())}")
    m = d["meta"]
    nmax = m.get("null_max") or 0.0
    out += [str(len(m["real_ge7"])), f"{len(m['null_ge7'])} ({nmax:.1f})",
            f"{m['masked']:.3f}"]
    return out


def main(variants: list[str]) -> None:
    before = Path("cache/movers/campaign/units")
    print("| Field | Variant | 20-50 | 50-100 | 100-200 | 200-400 | Real >= 7 | Null >= 7 (max) "
          "| Masked | Lost / gained (paired) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for f in FIELDS:
        b = load(before, f)
        print(f"| {f} | before | " + " | ".join(cells(b)) + " | |")
        for v in variants:
            a = load(Path("cache/movers/fixruns") / v, f)
            if a is None:
                print(f"| {f} | {v} | (missing) |")
                continue
            assert np.allclose(a["flux"], b["flux"]), "injections differ: not paired"
            lost = b["rec"] & ~a["rec"]
            gained = a["rec"] & ~b["rec"]
            slow = f" (lost at < 0.5 px/day: {int((lost & (a['rate'] < 0.5)).sum())})"
            print(f"| {f} | {v} | " + " | ".join(cells(a)) +
                  f" | {int(lost.sum())} / {int(gained.sum())}{slow} |")


if __name__ == "__main__":
    main(sys.argv[1:])
