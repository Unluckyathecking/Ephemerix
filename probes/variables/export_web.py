"""Write web/data/variability.json: the relative light curves of R Dra and RW Aur shown on their views.

Only what passed the checks in verify.py and verify_followup.py (15 Nov 2026) is exported:
R Dra at 0.75-1.1 um (detector 1) and 4.4-5.0 um (detector 6); RW Aur at 3.8-5.0 um (detectors 5 and 6).
Every number in the JSON is computed here from the cached wing photometry in cache/variables/lc/
(rdra_lc.py, verify.py, rwaur_wing.py), except the catalogue period (AAVSO VSX) and the NEOWISE fit
(rdra_wise_phase.py), which are copied with their source.

Usage (from probes/variables): uv run python export_web.py
"""
import json
from datetime import UTC, datetime, timedelta

import numpy as np

from analysis import LC, ROOT, relative, robust_std, sine_fit
from verify import P_VSX, T0, arrays, fit, periodogram
from verify_followup import boot_amp, single_pass_mask

OUT = ROOT / "web" / "data" / "variability.json"
BAND = {1: "0.75-1.1 µm", 3: "1.65-2.4 µm", 4: "2.4-3.8 µm", 5: "3.8-4.4 µm", 6: "4.4-5.0 µm"}
MJD0 = datetime(1858, 11, 17, tzinfo=UTC)
SEED = 3


def iso(mjd: float) -> str:
    return (MJD0 + timedelta(days=float(mjd))).date().isoformat()


def mag(mean: float, amp: float) -> float:
    """Peak-to-peak in magnitudes of a sine with this mean and semi-amplitude (relative units)."""
    return float(2.5 * np.log10((mean + amp) / (mean - amp))) if mean - amp > 0 else float("nan")


def r3(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def points(a: dict, k: int, sig: float, flagged: np.ndarray) -> list:
    s = (a["det"] == k) & (np.isfinite(a["rel"]) | flagged)
    return [[round(float(a["mjd"][i]), 3), r3(a["rel_all"][i]), r3(sig), int(a["pass"][i]),
             "template from one pass only" if flagged[i] else ""] for i in np.where(s)[0]]


def star_series(name: str) -> dict:
    a = arrays(json.loads((LC / f"{name}-diag.json").read_text()))
    a["rel_all"] = a["rel"].copy()
    flagged = single_pass_mask(a)
    a["rel"] = np.where(flagged, np.nan, a["rel"])
    return a, flagged


def rdra() -> dict:
    rng = np.random.default_rng(SEED)
    a, flagged = star_series("r-dra")
    bands = []
    for k in (1, 6):
        s = (a["det"] == k) & np.isfinite(a["rel"])
        amp, _, ph, sig, d2 = fit(a["mjd"][s], a["rel"][s], P_VSX)
        c, *_ = sine_fit(a["mjd"][s] - T0, a["rel"][s], np.full(s.sum(), sig), P_VSX)
        b = boot_amp(a, k, rng)
        alo, ahi = np.percentile(b[:, 0], [16, 84])
        plo, phi = np.percentile(b[:, 1], [16, 84])
        drops = []  # leave out one pass at a time (passes with points in this band)
        for p in np.unique(a["pass"][s]):
            keep = s & (a["pass"] != p)
            if keep.sum() >= 12:
                da, _, dp, *_ = fit(a["mjd"][keep], a["rel"][keep], P_VSX)
                drops.append((abs(da / amp - 1), abs(dp - ph)))
        bands.append({"det": k, "label": BAND[k], "n": int(s.sum()), "points": points(a, k, sig, flagged),
                      "drop_one_pass": {"max_amp_change": r3(max(x[0] for x in drops)), "max_phase_shift": r3(max(x[1] for x in drops))},
                      "fit": {"mean": r3(c[0]), "semi_amp": r3(amp), "semi_amp_68": [r3(alo), r3(ahi)],
                              "phase_of_max": r3(ph), "phase_of_max_68": [r3(plo), r3(phi)],
                              "mag_pk": round(mag(c[0], amp), 2), "mag_pk_68": [round(mag(c[0], alo), 2), round(mag(c[0], ahi), 2)],
                              "ratio_pk": round(float((c[0] + amp) / (c[0] - amp)), 1), "scatter": r3(sig), "delta_chi2": round(d2)}})
    # per-pass median of D1 and D6 together (passes with >= 5 points); brightest and faintest among those with >= 15
    passes = []
    for p in np.unique(a["pass"]):
        m = (a["pass"] == p) & np.isin(a["det"], (1, 6)) & np.isfinite(a["rel"])
        if m.sum() >= 5:
            passes.append({"pass": int(p), "mjd": round(float(a["mjd"][m].mean()), 1), "date": iso(a["mjd"][m].mean()),
                           "rel": r3(np.median(a["rel"][m])), "n": int(m.sum())})
    well = [q for q in passes if q["n"] >= 15]  # min_pass_exposures_for_dates
    bright = max(well, key=lambda q: q["rel"])
    faint = min(well, key=lambda q: q["rel"])
    ctrl, cflag = star_series("control-2m1640")
    cbands = []
    for k in (1, 6):
        s = (ctrl["det"] == k) & np.isfinite(ctrl["rel"])
        amp, _, _, sig, _ = fit(ctrl["mjd"][s], ctrl["rel"][s], P_VSX)
        cbands.append({"det": k, "label": BAND[k], "points": points(ctrl, k, sig, cflag), "semi_amp": r3(amp), "scatter": r3(sig)})
    c2, _ = star_series("control-2m1628")
    second = {}
    for k in (1, 6):
        s = (c2["det"] == k) & np.isfinite(c2["rel"])
        second[str(k)] = r3(fit(c2["mjd"][s], c2["rel"][s], P_VSX)[0])
    periods = np.exp(np.linspace(np.log(60), np.log(1500), 600))
    pg = periodogram(a, (1, 6), periods)
    bs = []
    ok_passes = np.unique(a["pass"][np.isfinite(a["rel"])])
    for _ in range(200):
        idx = np.concatenate([np.where(a["pass"] == p)[0] for p in rng.choice(ok_passes, len(ok_passes))])
        bb = {q: v[idx] for q, v in a.items()}
        bb["mjd"] = bb["mjd"] + rng.normal(0, 1e-3, len(idx))
        try:
            bs.append(periods[np.argmax(periodogram(bb, (1, 6), periods))])
        except np.linalg.LinAlgError:
            pass
    q = np.percentile(bs, [2.5, 16, 84, 97.5])
    return {
        "name": "R Draconis", "kind": "Mira variable (pulsating red giant)",
        "catalogue": {"period_days": P_VSX, "t0_max_mjd": T0, "source": "AAVSO VSX, OID 13673 (via VizieR B/vsx/vsx, fetched 2026-11-14)"},
        "checks": {"written_before_looking": 6, "source": "probes/variables/verify.py docstring"},
        "min_pass_exposures_for_dates": 15,
        "bands": bands, "passes": passes, "brightest_pass": bright, "faintest_pass": faint,
        "span": [iso(a["mjd"].min()), iso(a["mjd"].max())], "n_exposures": int(len(a["mjd"])),
        "control": {"name": "2MASS J16405512+6435204", "ks_mag": 2.105, "note": "a star of similar brightness 2.3 degrees away, measured the same way in its own frames",
                    "bands": cbands,
                    "second": {"name": "2MASS J16282110+6702385", "ks_mag": 1.909, "semi_amp": second}},
        "period_search": {"best_days": round(float(periods[np.argmax(pg)])), "range_68": [round(q[1]), round(q[2])],
                          "range_95": [round(q[0]), round(q[3])], "detectors": [1, 6],
                          "method": "sine fit per detector, delta chi-squared summed, 60-1500 d; ranges from 200 bootstrap resamples of whole passes"},
        "neowise": {"visits": 22, "years": "2014-2024", "semi_amp_mag": {"W1": 0.33, "W2": 0.31},
                    "note": "per-visit medians follow the same catalogue ephemeris; WISE also saturates on R Dra, so this is a consistency check, not a calibration",
                    "source": "IRSA TAP neowiser_p1bs_psd, probes/variables/rdra_wise_phase.py"},
        "failed": [
            {"band": BAND[3], "why": "a second comparison star, measured the same way, swings 0.43 times as much as R Draconis here, so we cannot separate the star from the method", "source": "probes/variables/verify.py, check F2"},
            {"band": BAND[4], "why": "the amplitude changes by up to 125% when a single pass is left out, so it rests on one pass", "source": "probes/variables/verify.py, check F5"},
            {"band": "1.1-1.65 and 3.8-4.4 µm", "why": "too few exposures with an unsaturated ring (fewer than 15)", "source": "probes/variables/verify.py"},
        ],
        "caveats": [
            "Relative brightness only: each point is the star divided by its own average at the same wavelength, so there is no calibrated flux.",
            "The centre of the star saturates every SPHEREx detector; we measure a ring 9 to 13 pixels from the centre, where it does not.",
            "Error bars are the scatter of the points about the fitted curve, not the pipeline's formal errors.",
        ],
    }


def rwaur() -> dict:
    def series(name):
        rows = json.loads((LC / f"{name}-wing.json").read_text())["rows"]
        mjd, det, wl = (np.array([r[k] for r in rows], float) for k in ("mjd", "det", "wl"))
        f = np.array([np.nan if r["wing"] is None else r["wing"] for r in rows], float)
        rel, _ = relative(wl, det, f, np.ones_like(f), frac=1 / 60, min_n=4)
        pas = np.concatenate([[0], np.cumsum(np.diff(mjd) > 20)]) if np.all(np.diff(mjd) >= 0) else None
        o = np.argsort(mjd)
        mjd, det, rel = mjd[o], det[o], rel[o]
        pas = np.concatenate([[0], np.cumsum(np.diff(mjd) > 20)])
        out = []
        for k in range(1, 7):
            s = (det == k) & np.isfinite(rel)
            per = [{"pass": int(p), "date": iso(mjd[s & (pas == p)].mean()), "rel": r3(np.median(rel[s & (pas == p)])),
                    "err": r3(robust_std(rel[s & (pas == p)]) / np.sqrt((s & (pas == p)).sum())), "n": int((s & (pas == p)).sum())}
                   for p in np.unique(pas[s])]
            out.append({"det": k, "label": BAND.get(k, "1.1-1.65 µm" if k == 2 else ""), "passes": per,
                        "points": [[round(float(mjd[i]), 3), r3(rel[i]), int(pas[i])] for i in np.where(s)[0]] if k in (5, 6) else []})
        return out
    return {
        "name": "RW Aurigae", "kind": "young T Tauri star, irregular variable",
        "bands": series("rw-aur"),
        "control": {"name": "2MASS J05072728+3022599", "ks_mag": 6.37,
                    "note": "a star 5 arcminutes away measured the same way in RW Aur's frames; it is fainter than RW Aur at 4 to 5 µm, so its points scatter more",
                    "bands": series("control-2m0507bright")},
        "headline_dets": [5, 6],
        "core_unsaturated": {"n": 21, "of": 335, "source": "probes/variables/rwaur.py on cache/variables/lc/rw-aur.json (14 Nov core photometry)"},
        "caveats": [
            "Relative brightness only, from a ring 9 to 13 pixels from the centre, because the centre saturates.",
            "SPHEREx saw RW Aur on three visits about six months apart, so we cannot say how it varied in between.",
            "At 0.75-3.8 µm its changes are no larger than the comparison star's, so there we cannot tell.",
        ],
    }


def main():
    out = {"generated": "2026-11-15", "script": "probes/variables/export_web.py",
           "method": "SPHEREx forced photometry in a 9-13 px ring around a saturated star, background from r >= 13.5 px, each exposure divided by the median of same-detector exposures within 1/60 of its wavelength (all epochs)",
           "data": "IRSA SIA collections spherex_dr1, spherex_qr3, spherex_dr1_deep, spherex_qr3_deep (frame lists of 2026-11-14), up to 400 exposures per star",
           "stars": {"r-draconis": rdra(), "rw-aurigae": rwaur()}}
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print("wrote", OUT, OUT.stat().st_size, "bytes")
    r = out["stars"]["r-draconis"]
    for b in r["bands"]:
        print(b["label"], b["fit"])
    print("bright", r["brightest_pass"], "faint", r["faintest_pass"], "period", r["period_search"])
    for b in out["stars"]["rw-aurigae"]["bands"]:
        print("RW", b["label"], [(p["date"], p["rel"], p["err"]) for p in b["passes"]])


if __name__ == "__main__":
    main()
