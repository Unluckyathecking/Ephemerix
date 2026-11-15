"""Summary of the 12-field mover-search campaign for the site: web/data/movers.json.

    python -m pxs.movers.summary [--campaign cache/movers/campaign]
        [--vet-report cache/movers/vet_report.json] [--out web/data/movers.json]

Reads the merged <field>.npz/.json files (`python -m pxs.movers.campaign merge`) and the
classifier gate report (`python -m pxs.movers.train_vet`). Completeness per field and pooled,
in four fixed flux bins and in the 8 log bins the 50%/90%
limits are interpolated from, with 95% Wilson intervals; known bodies recovered blind; real
versus mirrored-null peak counts; the classifier gate; the caveats as sentences. The output
has no timestamp and rounded floats, so unchanged inputs give the same bytes.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .completeness import Curve, Trial, curve
from .core import THRESHOLD
from .geometry import D_MAX_AU, pass_geometry
from .inject import Synthetic
from .limits import ab_mag, motion_distance, vmag_from_1um
from .search import MIN_MOTION_PX

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_DATE = "2026-11-14"
PIXSCALE_ARCSEC = 6.15
COARSE_EDGES_UJY = (20.0, 50.0, 100.0, 200.0, 400.0)
N_LOG_BINS = 8  # the binning the documented 50%/90% limits are interpolated in
Z95 = 1.959964

# Field order and display names. kind: "tno" holds a catalogued TNO, "blank" a high-latitude
# field, "control" a high-proper-motion star (artefact control).
FIELDS = (
    ("Haumea", "Haumea", "tno"), ("Makemake", "Makemake", "tno"), ("Eris", "Eris", "tno"),
    ("B1", "B1", "blank"), ("B2", "B2", "blank"), ("B3", "B3", "blank"), ("B4", "B4", "blank"),
    ("B5", "B5", "blank"), ("B6", "B6", "blank"), ("B7", "B7", "blank"),
    ("BarnardsStar", "Barnard's Star", "control"), ("WISE0855", "WISE 0855 (pass 1)", "control"),
)
# Catalogued TNOs: Horizons grid pixel at mid-pass (copied from FIELDS in
# deploy/modal_movers.py, which cannot be imported here), V and distance from
# probes/movers/gate1.py.
KNOWN = {
    "Haumea": {"name": "Haumea", "xy": (127.0, 137.0), "v": 17.3, "delta_au": 49},
    "Makemake": {"name": "Makemake", "xy": (46.0, 119.0), "v": 17.1, "delta_au": 52},
    "Eris": {"name": "Eris", "xy": (136.0, 68.0), "v": 18.7, "delta_au": 96},
}

CAVEATS = (
    ("One pass of one 20 arcmin field at a time: a body is searched only while it stays in "
    "that field during the pass, and nothing found here has been followed up."),
    ("Only the densest window of at most 16 days in each pass is searched, because the "
    "straight-line trajectory model drifts by more than half a pixel beyond that; frames "
    "outside the window are dropped."),
    ("At S/N 7 the real sky gives about as many peaks as the mirrored null search, field by "
    "field, so the cut sits at the noise and artefact floor and no peak is a candidate."),
    ("The two control fields (Barnard's Star and WISE 0855) gave many more peaks at S/N 7 or "
    "above than the blank fields, and their mirrored nulls gave as many. The cause is not "
    "established."),
    ("Injections are pooled over rate and distance, so holes in the trajectory grid narrower "
    "than one flux bin would not show in these curves."),
    ("The completeness limits are in flux. Turning them into a distance for a planet also "
    "needs the body to move at least 1.5 px within the pass, which caps the distance per "
    "field and is not folded into the flux curves."),
    ("A vetting classifier trained on these fields did not beat the plain S/N cut on held-out "
    "fields, so it is not shipped and does not affect any label."),
)


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials ((0, 1) when n is 0)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def _r(x: float, nd: int = 3) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _bin_row(k: int, n: int, **where: float) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {**where, "k": int(k), "n": int(n), "frac": _r(k / n) if n else None,
            "ci95": [_r(lo), _r(hi)]}


def coarse_bins(flux_ujy: np.ndarray, rec: np.ndarray) -> list[dict[str, Any]]:
    """Recovered / injected in the fixed flux bins of the documentation table."""
    rows = []
    for lo, hi in itertools.pairwise(COARSE_EDGES_UJY):
        m = (flux_ujy >= lo) & (flux_ujy < hi)
        rows.append(_bin_row(int(rec[m].sum()), int(m.sum()), lo_ujy=lo, hi_ujy=hi))
    return rows


def log_curve(flux_mjy: np.ndarray, rec: np.ndarray) -> tuple[list[dict[str, Any]], Curve]:
    """The N_LOG_BINS log-flux bins of completeness.curve, with counts and Wilson intervals."""
    trials = [Trial(Synthetic(0, 0, 0.0, 0.0, 0, float(f)), 0.0, bool(k), math.nan, math.nan)
              for f, k in zip(flux_mjy, rec)]
    c = curve(trials, n_bins=N_LOG_BINS)
    rows = [_bin_row(int(np.rint(frac * n)) if n else 0, int(n), flux_ujy=_r(f * 1e3, 2))
            for f, frac, n in zip(c.flux_mjy, c.completeness, c.n)]
    return rows, c


def limits(c: Curve) -> dict[str, float | None]:
    """50% and 90% completeness flux (uJy at 1 um), with V and AB at 1 um."""
    out: dict[str, float | None] = {}
    for tag, level in (("50", 0.5), ("90", 0.9)):
        f = c.flux_at(level) * 1e3
        out[f"flux{tag}_ujy"] = _r(f, 1)
        out[f"vmag{tag}"] = _r(vmag_from_1um(f), 2) if math.isfinite(f) else None
        out[f"ab1um{tag}"] = _r(ab_mag(f), 2) if math.isfinite(f) else None
    return out


def motion_limit_au(meta: dict[str, Any]) -> float:
    """Largest distance at which a body at rest moves MIN_MOTION_PX within the searched
    window (capped at the search's 1000 au), as in probes/movers/figures.py."""
    mjd = np.linspace(*meta["pass_mjd"], 40)
    geom = pass_geometry(meta["ra"], meta["dec"], mjd, PIXSCALE_ARCSEC)
    return min(motion_distance(geom, MIN_MOTION_PX), D_MAX_AU)


def peak_counts(meta: dict[str, Any], z: dict[str, np.ndarray]) -> dict[str, Any]:
    """Real-sky and mirrored-null peaks at S/N >= 5 and >= 7; real excludes the catalogued
    TNO (sample label 2)."""
    real, null = z["R"] == "real", z["R"] == "null"
    if int(real.sum()) != meta["n_real_ge5"] or int(null.sum()) != meta["n_null_ge5"]:
        raise ValueError(f"{meta['name']}: sample counts disagree with the field metadata")
    other = real & (z["Y"] != 2)
    s_other, s_null = z["S"][other], z["S"][null]
    hi_other, hi_null = s_other[s_other >= THRESHOLD], s_null[s_null >= THRESHOLD]
    return {"real_ge5": int(other.sum()), "null_ge5": int(null.sum()),
            "real_ge7": int(hi_other.size), "null_ge7": int(hi_null.size),
            "real_max": _r(s_other.max(), 2) if s_other.size else None,
            "null_max": _r(s_null.max(), 2) if s_null.size else None}


def known_body(name: str, meta: dict[str, Any], z: dict[str, np.ndarray]) -> dict[str, Any] | None:
    """The catalogued TNO of a field as recovered blind, or None if it was not."""
    k = KNOWN.get(name)
    tno = z["S"][(z["R"] == "real") & (z["Y"] == 2)]
    if k is None or not tno.size:
        return None
    snr = float(tno.max())
    i = int(np.argmin([abs(s - snr) for s in meta["real_ge7"]]))
    x, y = meta["real_ge7_xy"][i]
    off = math.hypot(x - k["xy"][0], y - k["xy"][1])
    real = z["S"][z["R"] == "real"]
    return {"name": k["name"], "field": name, "v": k["v"], "delta_au": k["delta_au"],
            "snr": _r(snr, 1), "rank": int(np.sum(real > snr)) + 1,
            "offset_px": _r(off, 1), "offset_arcsec": _r(off * PIXSCALE_ARCSEC, 1)}


def field_summary(name: str, label: str, kind: str, meta: dict[str, Any],
                  z: dict[str, np.ndarray]) -> dict[str, Any]:
    flux_mjy, rec = z["inj_flux"], z["inj_rec"].astype(bool)
    rows, c = log_curve(flux_mjy, rec)
    return {
        "key": name, "label": label, "kind": kind,
        "ra": _r(meta["ra"], 4), "dec": _r(meta["dec"], 4), "pass_index": meta["pass_index"],
        "pass_mjd": [_r(m, 3) for m in meta["pass_mjd"]],
        "span_days": _r(meta["pass_mjd"][1] - meta["pass_mjd"][0], 1),
        "frames_searched": meta["n_frames"], "frames_in_pass": meta["n_pass_frames"],
        "n_trials": meta["n_trials"], "masked_fraction": _r(meta["masked"], 3),
        "motion_limit_au": _r(motion_limit_au(meta), 0),
        "n_injected": int(rec.size), "n_recovered": int(rec.sum()),
        "bins": coarse_bins(flux_mjy * 1e3, rec), "curve": rows, "limits": limits(c),
        "peaks": peak_counts(meta, z), "extras_per_run": [int(e) for e in z["extras"]],
    }


def pooled_summary(arrays: list[dict[str, np.ndarray]]) -> dict[str, Any]:
    flux_mjy = np.concatenate([z["inj_flux"] for z in arrays])
    rec = np.concatenate([z["inj_rec"] for z in arrays]).astype(bool)
    rows, c = log_curve(flux_mjy, rec)
    return {"n_injected": int(rec.size), "n_recovered": int(rec.sum()),
            "bins": coarse_bins(flux_mjy * 1e3, rec), "curve": rows, "limits": limits(c)}


def classifier_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Gate numbers from train_vet's report: held-out recall of the S/N cut and each model
    at no more false positives than the cut."""
    variants = {name: {"recall": _r(m["recall_model"]), "tnos_kept": m["real_tnos_kept"],
                       "gate_passed": m["gate_passed"]} for name, m in report["variants"].items()}
    any_v = next(iter(report["variants"].values()))
    return {"train_fields": report["train_fields"], "test_fields": report["test_fields"],
            "n_train": report["n_train"], "n_test_positives": any_v["n_pos"],
            "n_test_negatives": any_v["n_neg"], "fp_per_test_field": _r(any_v["fp_per_field"], 2),
            "recall_snr_cut": _r(any_v["recall_snr_cut"]), "min_gain": 0.05,
            "variants": variants,
            "passed": any(v["gate_passed"] for v in variants.values()), "shipped": False}


def build(metas: dict[str, dict[str, Any]], arrays: dict[str, dict[str, np.ndarray]],
          report: dict[str, Any]) -> dict[str, Any]:
    names = [f for f in FIELDS if f[0] in metas]
    if not names:
        raise ValueError("no campaign fields found")
    fields = [field_summary(n, lab, kind, metas[n], arrays[n]) for n, lab, kind in names]
    known = [k for k in (known_body(n, metas[n], arrays[n]) for n, _, _ in names) if k]
    return {
        "schema": 1,
        "campaign": {"date": CAMPAIGN_DATE, "n_fields": len(fields), "field_arcmin": 20,
                     "threshold_snr": THRESHOLD, "min_motion_px": MIN_MOTION_PX,
                     "pixscale_arcsec": PIXSCALE_ARCSEC, "max_span_days": 16,
                     "injections": {"per_field": fields[0]["n_injected"], "flux_ujy": [20, 400],
                                    "distance_au": [30, 1000], "reference_um": 1.0},
                     "trials_range": [min(m["n_trials"] for m in metas.values()),
                                      max(m["n_trials"] for m in metas.values())]},
        "pooled": pooled_summary([arrays[n] for n, _, _ in names]),
        "fields": fields, "known_bodies": known,
        "classifier": classifier_summary(report), "caveats": list(CAVEATS),
    }


def load(campaign: Path) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]]]:
    metas, arrays = {}, {}
    for name, _, _ in FIELDS:
        jp, zp = campaign / f"{name}.json", campaign / f"{name}.npz"
        if jp.exists() and zp.exists():
            metas[name] = json.loads(jp.read_text())
            with np.load(zp) as z:
                arrays[name] = {k: z[k] for k in ("S", "Y", "R", "inj_flux", "inj_rec", "extras")}
    return metas, arrays


def render(campaign: Path, vet_report: Path) -> str:
    metas, arrays = load(campaign)
    report = json.loads(vet_report.read_text())
    return json.dumps(build(metas, arrays, report), indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.movers.summary", description=__doc__)
    ap.add_argument("--campaign", type=Path, default=ROOT / "cache/movers/campaign")
    ap.add_argument("--vet-report", type=Path, default=ROOT / "cache/movers/vet_report.json")
    ap.add_argument("--out", type=Path, default=ROOT / "web/data/movers.json")
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.campaign, args.vet_report))
    sys.stdout.write(f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
