"""Degradation test of the type gate, from the published views only (no download).

    uv run python probes/assembly/faint_degrade.py [trials per cell, default 150]

Each of the eight gallery targets whose type passes is made fainter: its combined spectrum
(web/gallery/<slug>/manifest.json, spx-all) is interpolated to the wavelength bins of a noise
field, scaled until its noiseless fit significance (match.detection_sigma) is 5, 8, 13, 19,
30 or 50, and given Gaussian noise drawn from that field's errors. Noise fields: the three
faint gallery targets (CWISE 1055, 0411, 0623) and "own" (the target's own error pattern).
Every trial goes through pxs.spectra.chosen_match and pxs.typegate.vet (neighbour checks
clear, target seen) and is scored by pxs.validation.rules.type_check against the published
type. Printed: the share of types that miss the published type, with Clopper-Pearson 95%
intervals, for spectra that fail the count (the faint rule) by measured significance, and for
spectra that pass the count (range floor of one subtype) by target and by noise field.
Seeds are fixed, so the numbers repeat.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.stats import beta

from pxs.spectra import chosen_match
from pxs.typegate import faint_reason, vet
from pxs.validation.rules import PASS, type_check

REPO = Path(__file__).resolve().parents[2]
GALLERY = REPO / "web" / "gallery"
PUBLISHED = {t["slug"]: t["known_type"]
             for t in json.loads((REPO / "data" / "targets.json").read_text())}
BRIGHT = ("epsilon-indi-b", "wisea-1101-5400", "cwise-2112-0529", "cwise-2029-7910",
          "denis-0255-4700", "2mass-0559-1404", "2mass-0415-0935", "ugps-0722-0540")
FIELDS = ("cwise-1055-5443", "cwise-0411-4714", "cwise-0623-0715", "own")
LEVELS = (5.0, 8.0, 13.0, 19.0, 30.0, 50.0)
S_BINS = (10.0, 13.0, 16.0, 20.0, 30.0, 1e9)
LATE = ("T7", "T8", "T9", "Y0", "Y1")


def points(slug: str) -> list[dict]:
    """Usable points of the published combined spectrum."""
    m = json.loads((GALLERY / slug / "manifest.json").read_text())
    spec = next(s for s in m["spectra"] if s["id"] == "spx-all")
    return [p for p in spec["points"] if not p["flagged"] and p["flux"] is not None and p["err"]]


def with_flux(base: list[dict], flux: np.ndarray) -> dict:
    return {"id": "spx-all", "points": [{**p, "flux": float(f)} for p, f in zip(base, flux)]}


def scaled_signal(base: list[dict], shape: np.ndarray, level: float) -> np.ndarray:
    """`shape` scaled so that, alone and with base's errors, its fit significance is `level`
    (bisection: the 10% error floor makes the significance non-linear in the scale)."""
    lo, hi = 1e-7, 1e2
    for _ in range(36):
        mid = (lo * hi) ** 0.5
        if chosen_match([with_flux(base, mid * shape)])["detection_sigma"] < level:
            lo = mid
        else:
            hi = mid
    return shape * (lo * hi) ** 0.5


def cell(args: tuple[str, str, float, int]) -> list[dict]:
    bright, field, level, n = args
    src = points(bright)
    base = src if field == "own" else points(field)
    shape = np.interp([p["wl_um"] for p in base], [p["wl_um"] for p in src],
                      [p["flux"] for p in src])
    signal = scaled_signal(base, shape, level)
    err = np.array([p["err"] for p in base])
    rng = np.random.default_rng([BRIGHT.index(bright), FIELDS.index(field), int(level)])
    out = []
    for _ in range(n):
        spec = with_flux(base, signal + rng.normal(0.0, err))
        fit = chosen_match([spec])
        kept, _ = vet(fit, [spec], blended=False)
        row = {"bright": bright, "field": field, "faint": faint_reason(spec) is not None,
               "S": fit["detection_sigma"], "typed": kept is not None, "wrong": False,
               "late": kept is not None and kept["best"]["type"] in LATE}
        if kept is not None:
            row["wrong"] = type_check(kept, PUBLISHED[bright], True, None)["verdict"] != PASS
        out.append(row)
    return out


def interval(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(0.975, k + 1, n - k))
    return lo, hi


def line(label: str, rows: list[dict]) -> str:
    typed = [r for r in rows if r["typed"]]
    wrong = sum(r["wrong"] for r in typed)
    lo, hi = interval(wrong, len(typed))
    return (f"  {label:30s} trials {len(rows):5d}  typed {len(typed):5d}  wrong {wrong:4d} "
            f"({wrong / max(len(typed), 1):5.1%}, 95% {lo:.1%}-{hi:.1%})")


def report(rows: list[dict]) -> list[str]:
    faint = [r for r in rows if r["faint"] and r["field"] != "own"]
    out = ["FAINT RULE (fails the count; noise of the three faint fields), by measured S:"]
    for a, b in zip(S_BINS, S_BINS[1:]):
        out.append(line(f"S {a:g} to {b:g}" if b < 1e9 else f"S {a:g} and up",
                        [r for r in faint if a <= r["S"] < b]))
    out.append(line("S 10 to 16 (CWISE 1055: 12.9)", [r for r in faint if 10 <= r["S"] < 16]))
    for field in FIELDS[:-1]:
        out.append(line(f"S 10 to 16, field {field[6:10]}",
                        [r for r in faint if 10 <= r["S"] < 16 and r["field"] == field]))
    out.append(line("S 10 to 16, typed T7 or later",
                    [r for r in faint if 10 <= r["S"] < 16 and r["late"]]))
    out.append(line("all S", faint))
    out.append("SPECTRA THAT PASS THE COUNT (range floor of one subtype):")
    count = [r for r in rows if not r["faint"]]
    groups = defaultdict(list)
    for r in count:
        groups[f"field {r['field']}"].append(r)
        groups[f"target {r['bright']}"].append(r)
    out += [line(k, groups[k]) for k in sorted(groups)]
    out.append(line("three faint fields, all targets", [r for r in count if r["field"] != "own"]))
    out.append(line("same without Eps Ind B (pair)",
                    [r for r in count if r["field"] != "own" and r["bright"] != "epsilon-indi-b"]))
    return out


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    jobs = [(b, f, lv, n) for b in BRIGHT for f in FIELDS for lv in LEVELS]
    with ProcessPoolExecutor() as ex:
        rows = [r for part in ex.map(cell, jobs) for r in part]
    sys.stdout.write("\n".join(report(rows)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
