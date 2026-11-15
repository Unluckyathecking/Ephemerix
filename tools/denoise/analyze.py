"""The three gates from the gate unit files; writes result.json. Definitions: README.md.

    cd tools && uv run python -m denoise.analyze GATE_DIR [train_log.json [out.json]]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from pxs.movers.completeness import Trial, curve
from pxs.movers.inject import Synthetic

from .select_variant import flux_fit

BASE_THRESHOLD = 7.0
SEED = 5.0
GRID = np.round(np.arange(5.0, 12.0001, 0.05), 2)
LEVELS = (0.5, 0.9)
N_BOOT = 2000
FLUX_EDGES_MJY = 0.02 * 20.0 ** (np.arange(5) / 4)
ARMS = ("base", "den")


def load(gate_dir: Path) -> dict[str, dict[str, Any]]:
    """{field: {"null": {arm: snr array}, "real": {arm: (n, 3) array}, "src": [rows],
    "stats": dict}}; only fields with a base unit and at least one injection unit."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(gate_dir.glob("*__base.json")):
        b = json.loads(p.read_text())
        src = [s for q in sorted(gate_dir.glob(f"{b['name']}__inj*.json"))
               for s in json.loads(q.read_text())["sources"]]
        if not src:
            continue
        out[b["name"]] = {
            "null": {a: np.array([d[2] for d in b[a]["null"]], float) for a in ARMS},
            "real": {a: np.array(b[a]["real"], float).reshape(-1, 3) for a in ARMS},
            "src": src, "stats": b["den"]["stats"],
            "noise_scale": {a: b[a]["noise_scale_median"] for a in ARMS}}
    return out


def matched_threshold(null_base: np.ndarray, null_den: np.ndarray) -> tuple[int, float]:
    """(N0, lowest grid threshold at which the den null count is <= N0)."""
    n0 = int(np.sum(null_base >= BASE_THRESHOLD))
    ok = [t for t in GRID if np.sum(null_den >= t) <= n0]
    return n0, float(ok[0]) if ok else math.inf


def _trials(flux: np.ndarray, rec: np.ndarray) -> list[Trial]:
    return [Trial(Synthetic(0.0, 0.0, 0.0, 0.0, 0.0, float(f)), 0.0, bool(r), math.nan,
                  math.nan) for f, r in zip(flux, rec, strict=True)]


def limits(flux: np.ndarray, snr: np.ndarray, threshold: float) -> list[float]:
    """50% and 90% completeness fluxes (mJy) with the pipeline's curve and flux_at."""
    c = curve(_trials(flux, snr >= threshold))
    return [c.flux_at(level) for level in LEVELS]


def _interval(v: np.ndarray) -> dict[str, Any]:
    ok = v[np.isfinite(v)]
    if ok.size < 0.9 * v.size:
        return {"lo": None, "hi": None, "sd": None, "nan_fraction": 1 - ok.size / v.size}
    lo, hi = np.percentile(ok, [2.5, 97.5])
    return {"lo": float(lo), "hi": float(hi), "sd": float(ok.std()),
            "nan_fraction": 1 - ok.size / v.size}


def gate1(data: dict[str, dict[str, Any]], rng: np.random.Generator) -> dict[str, Any]:
    names = list(data)
    flux = {n: np.array([s["flux_mjy"] for s in data[n]["src"]]) for n in names}
    snr = {a: {n: np.array([s[a]["snr"] or 0.0 for s in data[n]["src"]]) for n in names}
           for a in ARMS}

    def run(pick: list[str], idx: list[np.ndarray]) -> tuple[int, float, list[float]]:
        n0, t1 = matched_threshold(np.concatenate([data[n]["null"]["base"] for n in pick]),
                                   np.concatenate([data[n]["null"]["den"] for n in pick]))
        f = np.concatenate([flux[n][i] for n, i in zip(pick, idx, strict=True)])
        sb = np.concatenate([snr["base"][n][i] for n, i in zip(pick, idx, strict=True)])
        sd = np.concatenate([snr["den"][n][i] for n, i in zip(pick, idx, strict=True)])
        lb, ld = limits(f, sb, BASE_THRESHOLD), limits(f, sd, t1)
        return n0, t1, lb + ld + [ld[k] / lb[k] for k in range(len(LEVELS))]

    full = [np.arange(len(flux[n])) for n in names]
    n0, t1, point = run(names, full)
    boot, t1s = [], []
    for _ in range(N_BOOT):
        pick = [names[i] for i in rng.integers(len(names), size=len(names))]
        _, tb, vals = run(pick, [rng.integers(len(flux[n]), size=len(flux[n])) for n in pick])
        boot.append(vals)
        t1s.append(tb)
    b = np.array(boot, float)
    keys = [f"{a}_f{int(100 * lv)}_ujy" for a in ARMS for lv in LEVELS]
    out: dict[str, Any] = {"n0_null_base_ge7": n0, "den_threshold": t1,
                           "den_threshold_boot": _interval(np.array(t1s)),
                           "n_sources": int(sum(len(v) for v in flux.values())),
                           "n_fields": len(names), "n_boot": N_BOOT}
    for k, key in enumerate(keys):
        out[key] = {"value": 1e3 * point[k]} | {
            q: (None if v is None else 1e3 * v) if q != "nan_fraction" else v
            for q, v in _interval(b[:, k]).items()}
    ok = True
    for k, lv in enumerate(LEVELS):
        r = {"value": point[4 + k]} | _interval(b[:, 4 + k])
        out[f"ratio_f{int(100 * lv)}"] = r
        ok &= r["hi"] is not None and r["hi"] < 1.0
    f_all = np.concatenate(list(flux.values()))
    sb, sd = (np.concatenate(list(snr[a].values())) for a in ARMS)
    out["same_threshold_7"] = {
        "base_recovered": int(np.sum(sb >= 7)), "den_recovered": int(np.sum(sd >= 7)),
        "den_only": int(np.sum((sd >= 7) & (sb < 7))),
        "base_only": int(np.sum((sb >= 7) & (sd < 7))),
        "den_f50_f90_ujy": [1e3 * v for v in limits(f_all, sd, BASE_THRESHOLD)]}
    out["pass"] = bool(ok)
    return out


def gate2(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [s for d in data.values() for s in d["src"]
            if s["base"]["forced"] is not None and s["den"]["forced"] is not None]
    f = np.array([s["flux_mjy"] for s in rows])
    fb, fd = (np.array([s[a]["forced"] for s in rows]) for a in ARMS)
    eb = np.array([s["base"]["forced_err"] for s in rows])
    keep = np.abs(fb - f) <= 5 * eb
    bins, ok = [], True
    edges = [(FLUX_EDGES_MJY[i], FLUX_EDGES_MJY[i + 1]) for i in range(4)] + [(0.0, math.inf)]

    def se(v: np.ndarray) -> float:
        return float(v.std(ddof=1) / math.sqrt(v.size)) if v.size > 1 else math.nan

    for lo, hi in edges:
        m = keep & (f >= lo) & (f < hi)
        shift = (fd - fb)[m] / f[m]
        rb, rd = (fb - f)[m] / f[m], (fd - f)[m] / f[m]
        row = {"lo_ujy": 1e3 * lo, "hi_ujy": 1e3 * hi if math.isfinite(hi) else None,
               "n": int(m.sum()), "bias_base": float(rb.mean()), "bias_base_se": se(rb),
               "bias_den": float(rd.mean()), "bias_den_se": se(rd),
               "shift": float(shift.mean()), "shift_se": se(shift)}
        row["pass"] = bool(abs(row["shift"]) <= max(2 * row["shift_se"], 0.01))
        ok &= row["pass"]
        bins.append(row)
    # Not part of the pass rule: the shift split into an additive and a proportional part.
    return {"n_sources": len(rows), "n_dropped_5sigma": int((~keep).sum()),
            "bins": bins[:-1], "overall": bins[-1], "pass": bool(ok),
            "den_minus_base_fit": flux_fit(1e3 * f, 1e3 * (fd - fb)),
            "base_minus_injected_fit": flux_fit(1e3 * f, 1e3 * (fb - f)),
            "den_minus_injected_fit": flux_fit(1e3 * f, 1e3 * (fd - f))}


def gate3(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def count(kind: str, arm: str, t: float) -> int:
        return int(sum(np.sum((d[kind][arm] if kind == "null" else d[kind][arm][:, 2]) >= t)
                       for d in data.values()))

    out: dict[str, Any] = {}
    for t in (5.0, 6.0, 7.0):
        out[f"ge{int(t)}"] = {f"{k}_{a}": count(k, a, t) for k in ("null", "real")
                              for a in ARMS}
    n7, n5 = out["ge7"], out["ge5"]
    out["per_field_null_ge7"] = {n: [int(np.sum(d["null"][a] >= 7)) for a in ARMS]
                                 for n, d in data.items()}
    out["per_field_null_ge5"] = {n: [int(d["null"][a].size) for a in ARMS]
                                 for n, d in data.items()}
    out["null_max"] = {n: [float(d["null"][a].max()) if d["null"][a].size else None
                           for a in ARMS] for n, d in data.items()}
    out["pass"] = bool(n7["null_den"] <= n7["null_base"]
                       and n5["null_den"] <= n5["null_base"] + math.sqrt(n5["null_base"]))
    return out


def main(gate_dir: Path, train_log: Path | None) -> dict[str, Any]:
    data = load(gate_dir)
    g1, g2, g3 = gate1(data, np.random.default_rng(0)), gate2(data), gate3(data)
    res: dict[str, Any] = {
        "fields": list(data), "gate1_completeness": g1, "gate2_flux": g2,
        "gate3_null_peaks": g3, "passed": bool(g1["pass"] and g2["pass"] and g3["pass"]),
        "held_out_variance_removed": {n: d["stats"] for n, d in data.items()},
        "noise_scale_median": {n: d["noise_scale"] for n, d in data.items()}}
    if train_log is not None and train_log.exists():
        log = json.loads(train_log.read_text())
        res["training"] = {k: v for k, v in log.items() if k not in ("epochs", "train_files")}
        res["training"]["final_epochs"] = log["epochs"][-3:]
    return json.loads(json.dumps(res, default=float))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3, 4):
        raise SystemExit("usage: analyze.py GATE_DIR [TRAIN_LOG_JSON [OUT_NAME]]")
    result = main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) >= 3 else None)
    out_name = sys.argv[3] if len(sys.argv) == 4 else "result.json"
    (Path(__file__).resolve().parent / out_name).write_text(
        json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("gate1_completeness", "gate2_flux",
                                             "gate3_null_peaks", "passed")}, indent=1))
