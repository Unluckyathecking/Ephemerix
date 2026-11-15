"""Merge the pilot's unit files into web/data/p9-search.json (numbers for the doc).

    modal volume get --force pxs-movers /p9/ cache/p9/units/
    PYTHONPATH=tools uv run python -m p9_search.vet       # survivors: catalogue checks
    PYTHONPATH=tools uv run python -m p9_search.report
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from pxs.movers.core import THRESHOLD
from pxs.movers.limits import vmag_from_1um

from . import limits as L
from . import population as P
from .tiles import CSV, KERNEL_DEG, TILE_ARCMIN, tile_area_deg2

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
UNITS = REPO / "cache" / "p9" / "units" / "p9"
VETTING = HERE / "vetting.json"
ASSESSMENT = HERE / "assessment.json"  # hand verdicts from the stamps (doc, "Peaks")
OUT = REPO / "web" / "data" / "p9-search.json"
PLANETX = REPO / "web" / "data" / "planetx-limits.json"
D_BINS_AU = ((30.0, 100.0), (100.0, 300.0), (300.0, 1000.0))  # pooled separately too
D_MAX_AU = 1000.0  # farthest injected (and searched) distance


def load_units(units: Path = UNITS) -> dict[str, dict[str, Any]]:
    """{tile: {"base": meta, "runs": [meta, ...]}} for tiles with a base unit."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(units.glob("*__base.json")):
        name = p.name.removesuffix("__base.json")
        runs = [json.loads(q.read_text()) for q in sorted(units.glob(f"{name}__run*.json"))]
        out[name] = {"base": json.loads(p.read_text()), "runs": runs}
    return out


def injections(runs: list[dict]) -> dict[str, np.ndarray]:
    keys = ("inj_flux", "inj_d", "inj_rec", "inj_rate", "inj_snr")
    return {k: np.concatenate([np.asarray(r["injections"][k], float) for r in runs])
            if runs else np.zeros(0) for k in keys}


def vetted_threshold(base: dict) -> float:
    """S/N a peak needed to be vetted individually: above the field's null maximum (and
    never below the search's threshold of 7)."""
    return max(THRESHOLD, base.get("null_max") or 0.0)


def recovered_above(rec: np.ndarray, snr: np.ndarray, threshold: float) -> np.ndarray:
    """Recovered (right position and rate) with recovered S/N above `threshold`."""
    s = np.nan_to_num(np.asarray(snr, float), nan=-np.inf)
    return (np.asarray(rec) > 0) & (s > threshold)


def survivors(base: dict) -> list[dict]:
    """Real peaks >= 7 brighter than the field's brightest mirrored-null peak."""
    nmax = base.get("null_max") or 0.0
    return [p for p in base["peaks_ge7"] if p["snr"] > nmax]


def field_summary(name: str, unit: dict) -> dict[str, Any]:
    """Per-field numbers. The limit ("completeness", flux50/90) counts an injection only if
    it was recovered above the field's vetted threshold (its null maximum), the same bar a
    real peak had to clear to be examined; "snr7" is the plain S/N >= 7 sensitivity."""
    b, inj = unit["base"], injections(unit["runs"])
    flux = inj["inj_flux"] * 1e3
    thr = vetted_threshold(b)
    bins = L.binned(flux, recovered_above(inj["inj_rec"], inj["inj_snr"], thr))
    f50, f90 = L.flux_at(bins, 0.5), L.flux_at(bins, 0.9)
    b7 = L.binned(flux, inj["inj_rec"] > 0)
    peaks = b["peaks_ge7"]
    return {
        "name": name, "ra": b["ra"], "dec": b["dec"], "pass_index": b["pass_index"],
        "pass_mjd": b["pass_mjd"], "n_frames_searched": b["n_frames"],
        "n_frames_in_pass": b["n_pass_frames"], "n_reference_frames": b["n_ref"],
        "n_trials": b["n_trials"], "masked_fraction": b["masked"],
        "d_motion_au": b["d_motion_au"], "n_injected": len(flux),
        "vetted_threshold_snr": thr,
        "n_recovered": int(np.sum(inj["inj_rec"] > 0)),
        "n_recovered_above_threshold": int(np.sum(bins["k"])), "completeness": bins,
        "flux50_ujy": f50, "flux90_ujy": f90, "vmag50": vmag_from_1um(f50),
        "vmag90": vmag_from_1um(f90),
        "snr7": {"completeness": b7, "flux50_ujy": L.flux_at(b7, 0.5),
                 "flux90_ujy": L.flux_at(b7, 0.9)}, "real_ge7": len(peaks), "null_ge7": len(b["null_ge7"]),
        "real_max": max((p["snr"] for p in peaks), default=None), "null_max": b["null_max"],
        "labels": {lab: sum(p["label"] == lab for p in peaks)
                   for lab in sorted({p["label"] for p in peaks})},
        "above_null_max": [{k: p[k] for k in (
            "rank", "label", "ra", "dec", "snr", "snr_first_half", "snr_second_half",
            "max_frame_share", "flux_ujy", "flux_err_ujy", "rate_arcsec_h", "pa_deg",
            "distance_au", "known_name", "nearest_bright_star_px", "half_consistent")}
            for p in survivors(b)],
        "warnings": b["warnings"], "n_known_objects": b["n_known_objects"],
        "container_s": b["total_s"] + sum(r["total_s"] for r in unit["runs"]),
    }


def pooled(units: dict, d_range: tuple[float, float] | None = None,
           snr7: bool = False) -> dict:
    """Completeness of all fields' injections together (each field at its vetted
    threshold, or at S/N 7 with snr7), optionally in one distance range."""
    inj = [injections(u["runs"]) for u in units.values()]
    thr = [THRESHOLD if snr7 else vetted_threshold(u["base"]) for u in units.values()]
    f = np.concatenate([i["inj_flux"] for i in inj]) * 1e3
    r = np.concatenate([recovered_above(i["inj_rec"], i["inj_snr"], t)
                        for i, t in zip(inj, thr)])
    d = np.concatenate([i["inj_d"] for i in inj])
    sel = np.ones_like(r) if d_range is None else (d >= d_range[0]) & (d < d_range[1])
    b = L.binned(f[sel], r[sel])
    f50, f90 = L.flux_at(b, 0.5), L.flux_at(b, 0.9)
    label = ("all injections" if d_range is None else
             f"injections at {d_range[0]:.0f}-{d_range[1]:.0f} au") + \
        (", recovered at S/N >= 7" if snr7 else ", recovered above each field's null maximum")
    return {"selection": label, "n": int(sel.sum()), "completeness": b, "flux50_ujy": f50,
            "flux90_ujy": f90, "vmag50": vmag_from_1um(f50), "vmag90": vmag_from_1um(f90)}


def population_comparison(fields: list[dict]) -> dict:
    """Expected fraction of the reference population (all, and survivors of ZTF/DES/PS1)
    that these fields exclude, from the members within KERNEL_DEG of each tile."""
    pop = P.load(CSV)
    xyz = P.unit_vectors(pop.ra, pop.dec)
    at = P.unit_vectors(np.array([f["ra"] for f in fields]), np.array([f["dec"] for f in fields]))
    near = P.members_near(xyz, at, KERNEL_DEG)
    cap = P.cap_area_deg2(KERNEL_DEG)
    area = tile_area_deg2()
    in_tiles = excl = excl_new = in_tiles_new = excl_motion = 0.0
    bright = []
    for f, idx in zip(fields, near):
        idx = np.asarray(idx, int)
        dens = len(idx) / len(pop) / cap
        comp = L.completeness_at(f["completeness"], L.flux_1um_from_vmag(pop.vmag[idx]))
        surv = pop.survives[idx].astype(float)
        in_tiles += dens * area
        in_tiles_new += dens * area * float(np.mean(surv)) if len(idx) else 0.0
        excl += L.excluded_fraction(dens, area, comp, pop.r_au[idx], D_MAX_AU)
        excl_new += L.excluded_fraction(dens, area, comp * surv, pop.r_au[idx], D_MAX_AU)
        excl_motion += L.excluded_fraction(dens, area, comp, pop.r_au[idx], f["d_motion_au"])
        bright.append(float(np.mean(pop.vmag[idx] <= f["vmag50"])) if len(idx) else math.nan)
    surv_all = pop.survives
    return {
        "kernel_deg": KERNEL_DEG,
        "fraction_of_population_in_fields": in_tiles,
        "fraction_of_population_in_fields_not_yet_excluded": in_tiles_new,
        "expected_fraction_excluded": excl,
        "expected_fraction_excluded_not_already_excluded_by_ztf_des_ps1": excl_new,
        "expected_fraction_excluded_if_capped_at_d_motion": excl_motion,
        "local_fraction_brighter_than_field_v50_median": float(np.nanmedian(bright)),
        "population_fraction_surviving_ztf_des_ps1": float(np.mean(surv_all)),
        "surviving_fraction_with_v_le_19_7": float(np.mean(pop.vmag[surv_all] <= 19.7)),
        "note": ("Positions at the 2018.4 epoch; local density from a top-hat kernel, so the "
                 "per-tile mass is a smoothed estimate. Completeness is interpolated at each "
                 "member's V converted to 1 um for a solar-coloured body; members beyond 1000 au "
                 "count as not excluded (the capped variant also drops members beyond the "
                 "field's at-rest motion distance)."),
    }


def planetx_reach(flux_lim_ujy: float) -> list[dict]:
    """Per planetx case: farthest tabulated distance (<= D_MAX_AU) at which its SPHEREx D1
    AB magnitude (the case's lo/nom/hi spread) is at least as bright as the limit."""
    px = json.loads(PLANETX.read_text())
    ab_lim = L.ab_from_ujy(flux_lim_ujy)
    out = []
    for c in px["cases"]:
        mags = c["ab"]["SPHEREx D1"]
        row = {"key": c["key"], "label": c["label"], "ab_limit_d1": ab_lim}
        for k in ("lo", "nom", "hi"):
            r = L.reach_au(px["distances_au"], mags[k], ab_lim)
            row[f"reach_{k}_au"] = None if r is None else min(r, D_MAX_AU)
        out.append(row)
    return out


def build() -> dict[str, Any]:
    units = load_units()
    fields = [field_summary(n, u) for n, u in units.items()]
    good = [f for f in fields if math.isfinite(f["flux90_ujy"])]
    y90 = max(f["flux90_ujy"] for f in good) if good else math.nan
    y50 = max(f["flux50_ujy"] for f in fields if math.isfinite(f["flux50_ujy"]))
    d_mot = [f["d_motion_au"] for f in fields]
    vet = json.loads(VETTING.read_text()) if VETTING.exists() else {}
    judged = json.loads(ASSESSMENT.read_text()) if ASSESSMENT.exists() else {}
    surv = [dict(s, field=f["name"], vetting=vet.get(f"{f['name']}#{s['rank']}"),
                 assessment=judged.get(f"{f['name']}#{s['rank']}"))
            for f in fields for s in f["above_null_max"]]
    pool = pooled(units)
    area = tile_area_deg2()
    real7 = sum(f["real_ge7"] for f in fields)
    null7 = sum(f["null_ge7"] for f in fields)
    n_exceed = sum(bool(f["above_null_max"]) for f in fields)
    return {
        "schema": 1,
        "claim": ("Upper limits from a pilot search of one SPHEREx pass per field. Not a "
                  "detection claim; no candidate planet is reported."),
        "tile_rule": json.loads((HERE / "tiles.json").read_text())["rule"] | {
            "source": json.loads((HERE / "tiles.json").read_text())["source"]},
        "statement": (
            f"Over {area * len(fields):.1f} deg^2 ({len(fields)} fields of 20 arcmin) of the "
            f"densest |b| > 15 deg part of the Brown & Batygin (2021) reference population, no "
            f"moving source brighter than {pool['flux90_ujy']:.0f} uJy at 1 um "
            f"(V ~ {pool['vmag90']:.1f}) at 30-1000 au in a single SPHEREx pass, at 90% "
            f"completeness pooled over the fields (50%: {pool['flux50_ujy']:.0f} uJy, "
            f"V ~ {pool['vmag50']:.1f}), apart from the {len(surv)} listed peaks above their "
            "field's null maximum. This excludes none of the favoured Planet Nine cases."),
        "n_fields": len(fields), "tile_arcmin": TILE_ARCMIN,
        "area_deg2": area * len(fields), "area_deg2_with_90pc_limit": area * len(good),
        "fields": fields,
        "pooled": pool, "pooled_by_distance": [pooled(units, r) for r in D_BINS_AU],
        "pooled_snr7": pooled(units, snr7=True),
        "worst_field_flux90_ujy": y90, "worst_field_vmag90": vmag_from_1um(y90),
        "worst_field_flux50_ujy": y50, "worst_field_vmag50": vmag_from_1um(y50),
        "d_motion_au": {"min": min(d_mot), "median": float(np.median(d_mot)),
                        "max": max(d_mot)},
        "peaks": {"real_ge7": real7, "null_ge7": null7,
                  "fields_with_real_peak_above_null_max": n_exceed,
                  "note": ("Real and mirrored-null searches are statistically alike, so in "
                           "pure noise about half the fields would have a real peak above "
                           "their null maximum.")},
        "unexplained_or_vetted_peaks_above_null_max": surv,
        "population": population_comparison(fields),
        "planetx_reach": {
            "note": ("SPHEREx D1 AB of each web/data/planetx-limits.json case (lo/nom/hi as "
                     "there) against the pooled limit; reach capped at 1000 au."),
            "at_pooled_flux50": planetx_reach(pool["flux50_ujy"]),
            "at_pooled_flux90": planetx_reach(pool["flux90_ujy"])},
        "container_hours": sum(f["container_s"] for f in fields) / 3600,
    }


def clean(v: Any) -> Any:
    """JSON-safe copy: non-finite floats become None, numpy scalars plain Python."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


def main() -> None:
    out = clean(build())
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("n_fields", "area_deg2", "worst_field_flux90_ujy",
                                          "worst_field_vmag90", "d_motion_au", "peaks",
                                          "container_hours")}, indent=1, default=float))


if __name__ == "__main__":
    main()
