"""Recovery statistics of the body-recovery campaign, from the per-(body, variant) records.

    uv run python tools/solarsystem_validation/analyse.py <results dir> \
        [--failures v1-failures.json] [--md body-recovery.md] \
        [--json web/data/body-recovery.json]

Pre-registered reading (fixed before the full run):
- The unit is the covered pass: a pass of the real track that the pipeline analysed
  (>= MIN_PASS_FRAMES read frames). Passes are binned by predicted V (median Horizons
  APmag over the pass's exposures). Intervals are Clopper-Pearson 95%.
- A body is recovered when any of its covered passes is recovered; a control track is a
  false detection when any of its covered passes would count as recovered.
- Faintest reliably recovered: the faintest V bin whose 95% lower bound is >= 0.5.
- "crowded field" is a label (|b| < 10 deg at the pass), not a diagnosis.

Campaign v1 ran under the earlier detection rule (best band S/N >= 5). `report` re-decides
every pass from its stored band S/N values under the pipeline's current rule
(pxs.solarsystem.pipeline.pass_outcome; the centroid was measured for every pass the old
rule passed, a superset of the new one) and gives the old numbers alongside as `before`.

Written with Claude Code.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import zlib
from collections import Counter
from pathlib import Path

from scipy.stats import beta

from pxs.solarsystem.pipeline import DETECTED, MARGINAL, pass_outcome
from pxs.spherex.config import PIXSCALE_ARCSEC

POSITION_GATE_ARCSEC = 2 * PIXSCALE_ARCSEC  # as measure.POSITION_GATE_ARCSEC (tested)

V_EDGES = [6.0, 10.0, 12.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 24.0, 27.0]
POST_HOC_SNR = [5.0, 8.0, 10.0, 15.0]  # chosen after the controls were seen; see doc
CROWDED_B_DEG = 10.0
SATURATED_SHARE = 0.5
RELIABLE_LOWER = 0.5
MARGINAL_CAUSE = "marginal only (one band; consistent with noise)"
BEFORE_RULE = "best control-corrected band S/N >= 5 (campaign v1 rule)"


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else float(beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a, k + 1, n - k))
    return round(lo, 4), round(hi, 4)


def _rate(k: int, n: int) -> dict:
    return {"n": n, "k": k, "frac": round(k / n, 4) if n else None,
            "ci95": list(clopper_pearson(k, n))}


def recovery_table(passes: list[dict], edges: list[float] = V_EDGES) -> list[dict]:
    rows = []
    for lo, hi in itertools.pairwise(edges):
        ps = [p for p in passes if p.get("vmag") is not None and lo <= p["vmag"] < hi]
        k = sum(p["recovered"] for p in ps)
        rows.append({"bin": f"{lo:g}-{hi:g}", "lo_v": lo, "hi_v": hi,
                     "n_detected": sum(p["detected"] for p in ps),
                     "n_marginal": sum(p.get("outcome") == MARGINAL for p in ps),
                     **_rate(k, len(ps)),
                     "bodies": sorted({p["_body"] for p in ps if "_body" in p})})
    return rows


def faintest_reliable(rows: list[dict]) -> str | None:
    ok = [r for r in rows if r["n"] and r["ci95"][0] is not None
          and r["ci95"][0] >= RELIABLE_LOWER]
    return max(ok, key=lambda r: r["lo_v"])["bin"] if ok else None


def body_outcome(rec: dict) -> str:
    """"recovered", or the cause of non-recovery for one real-track record."""
    if rec["status"] != "ok":
        kind = (rec.get("error") or {}).get("kind", "bug")
        return {"horizons": "Horizons failure", "timeout": "timeout",
                "network": "network failure"}.get(kind, "pipeline error (bug)")
    passes = rec["passes"]
    if any(p["recovered"] for p in passes):
        return "recovered"
    if not (rec.get("track") or {}).get("n_visits"):
        return "no coverage"
    if not passes:
        return "too few frames per pass"
    if all(p["n_saturated"] >= SATURATED_SHARE * max(p["n_measured"], 1) for p in passes):
        return "saturated"
    if any(p["detected"] for p in passes):
        return "detected off position"
    if any(p.get("outcome") == MARGINAL for p in passes):
        return MARGINAL_CAUSE
    if any(p.get("gal_b") is not None and abs(p["gal_b"]) < CROWDED_B_DEG for p in passes):
        return f"not detected, crowded field (|b| < {CROWDED_B_DEG:g} deg)"
    return "not detected"


def false_detections(recs: list[dict]) -> dict:
    ctl = [r for r in recs if r["variant"] != "real" and r["status"] == "ok"]
    passes = [p for r in ctl for p in r["passes"]]
    tracks = [r for r in ctl if r["passes"]]
    return {"passes": _rate(sum(p["recovered"] for p in passes), len(passes)),
            "passes_snr_only": _rate(sum(p["detected"] for p in passes), len(passes)),
            "tracks": _rate(sum(any(p["recovered"] for p in r["passes"]) for r in tracks),
                            len(tracks)),
            "hits": [{"pdes": r["body"]["pdes"], "variant": r["variant"],
                      "vmag": p.get("vmag"), "best_band": p["best_band"],
                      "best_snr": p["best_snr"], "recovered": p["recovered"]}
                     for r in ctl for p in r["passes"] if p["detected"]],
            "errors": sum(r["status"] != "ok" for r in recs if r["variant"] != "real"),
            "by_class": {c: _track_rates([r for r in ctl if (r["body"].get("cls") or "?") == c])
                         for c in sorted({r["body"].get("cls") or "?" for r in ctl})}}


def _track_rates(ctl: list[dict]) -> dict:
    passes = [p for r in ctl for p in r["passes"]]
    tracks = [r for r in ctl if r["passes"]]
    return {"passes": _rate(sum(p["recovered"] for p in passes), len(passes)),
            "tracks": _rate(sum(any(p["recovered"] for p in r["passes"]) for r in tracks),
                            len(tracks))}


def controls_fired(recs: list[dict]) -> dict[str, int]:
    """Per body: how many of its control tracks have a pass that would count as recovered."""
    out: Counter = Counter()
    for r in recs:
        if r["variant"] != "real" and r["status"] == "ok":
            out[r["body"]["pdes"]] += any(p["recovered"] for p in r["passes"])
    return dict(out)


def threshold_scan(recs: list[dict], thresholds: list[float] = POST_HOC_SNR) -> list[dict]:
    """POST HOC: false-detection and recovery rates if 'detected' needed S/N >= t.

    Not part of the pre-registered reading: the thresholds were picked after the control
    S/N distribution was seen. Same position gate as the main rule.
    """
    ok = [r for r in recs if r["status"] == "ok"]
    ctl = [p for r in ok if r["variant"] != "real" for p in r["passes"]]
    real = [p for r in ok if r["variant"] == "real" for p in r["passes"]]

    def hit(p: dict, t: float) -> bool:
        return bool(p["recovered"] and p["best_snr"] is not None and p["best_snr"] >= t)

    real_tracks = [r for r in ok if r["variant"] == "real"]
    out = []
    for t in thresholds:
        table = recovery_table([{**p, "recovered": hit(p, t)} for p in real])
        out.append({"snr_min": t, "control_passes": _rate(sum(hit(p, t) for p in ctl),
                                                           len(ctl)),
                    "real_passes": _rate(sum(hit(p, t) for p in real), len(real)),
                    "real_bodies": _rate(sum(any(hit(p, t) for p in r["passes"])
                                             for r in real_tracks), len(real_tracks)),
                    "faintest_reliable_bin": faintest_reliable(table),
                    "by_predicted_v": [{k: r[k] for k in ("bin", "n", "k", "ci95")}
                                       for r in table if r["n"]]})
    return out


def _pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 2)


def astrometry(passes: list[dict]) -> dict:
    cen = [p["centroid"]["total"] for p in passes if p["recovered"]]
    rc = [p["recentre"] for p in passes if p["recovered"] and p.get("recentre")
          and p["recentre"].get("applied")]
    tot = [(r["east_arcsec"] ** 2 + r["north_arcsec"] ** 2) ** 0.5 for r in rc]
    return {"centroid_n": len(cen), "centroid_median_arcsec": _pctl(cen, 0.5),
            "centroid_p90_arcsec": _pctl(cen, 0.9),
            "psf_fit_n": len(rc), "psf_fit_median_arcsec": _pctl(tot, 0.5),
            "psf_fit_p90_arcsec": _pctl(tot, 0.9)}


def pass_summary(rec: dict | None) -> dict:
    """Per-body numbers for the site table: covered passes, recovered, best S/N, V range."""
    ps = (rec or {}).get("passes") or []
    vs = [p["vmag"] for p in ps if p.get("vmag") is not None]
    snr = [p["best_snr"] for p in ps if p.get("best_snr") is not None]
    return {"n_passes": len(ps), "n_recovered": sum(p["recovered"] for p in ps),
            "best_snr": round(max(snr), 1) if snr else None,
            "vmag_min": round(min(vs), 2) if vs else None,
            "vmag_max": round(max(vs), 2) if vs else None}


def summarise(recs: list[dict], failures: list[dict] | None = None,
              sample: list[dict] | None = None) -> dict:
    real = [r for r in recs if r["variant"] == "real"]
    by_pdes = {r["body"]["pdes"]: r for r in real}
    passes = [{**p, "_body": r["body"]["name"], "_pdes": r["body"]["pdes"]} for r in real if r["status"] == "ok"
              for p in r["passes"]]
    outcomes = {r["body"]["pdes"]: body_outcome(r) for r in real}
    for f in failures or []:
        outcomes.setdefault(f["pdes"], f"container failure ({f['type']})")
    for b in sample or []:
        outcomes.setdefault(b["pdes"], "no result")
    names = {r["body"]["pdes"]: r["body"] for r in real} | {b["pdes"]: b for b in sample or []}
    causes: dict[str, list[str]] = {}
    for pdes, o in outcomes.items():
        if o != "recovered":
            causes.setdefault(o, []).append(pdes)
    by_cls: dict[str, Counter] = {}
    for pdes, o in outcomes.items():
        c = by_cls.setdefault(names.get(pdes, {}).get("cls", "?"), Counter())
        c["n"] += 1
        c["recovered"] += o == "recovered"
    table = recovery_table(passes)
    rec_passes = [p for p in passes if p["recovered"]]
    faint = max(rec_passes, key=lambda p: p["vmag"] or 0) if rec_passes else None
    walls = [r["wall_s"] for r in recs if r.get("wall_s") is not None]
    prov = next((r["provenance"] for r in recs if r.get("provenance")), {})
    fired = controls_fired(recs)
    fd = false_detections(recs)
    reliable = faintest_reliable(table)
    return {
        "schema": 1, "provenance": prov,
        "bodies": {"n": len(outcomes), "recovered": sum(o == "recovered" for o in
                                                        outcomes.values()),
                   "ci95": list(clopper_pearson(sum(o == "recovered" for o in
                                                    outcomes.values()), len(outcomes)))},
        "by_class": {k: {"n": v["n"], "recovered": v["recovered"],
                         "ci95": list(clopper_pearson(v["recovered"], v["n"]))}
                     for k, v in sorted(by_cls.items())},
        "passes": _rate(len(rec_passes), len(passes)),
        "by_predicted_v": table,
        "faintest_reliable_bin": reliable,
        "faintest_recovery": None if faint is None else {
            "name": faint["_body"], "vmag": faint["vmag"], "best_band": faint["best_band"],
            "best_snr": faint["best_snr"],
            "controls_fired": fired.get(faint["_pdes"], 0)},
        "astrometry": astrometry(passes),
        "post_hoc_snr_thresholds": threshold_scan(recs),
        "false_detections": fd,
        "headline": headline(reliable, fd),
        "failures_by_cause": {k: sorted(v) for k, v in sorted(causes.items())},
        "outcomes": [{"pdes": p, "name": names.get(p, {}).get("name", p),
                      "cls": names.get(p, {}).get("cls"), "outcome": o,
                      "controls_fired": fired.get(p, 0), **pass_summary(by_pdes.get(p))}
                     for p, o in sorted(outcomes.items(), key=lambda x: x[0])],
        "max_body_wall_s": max(walls) if walls else None,
    }


def headline(reliable: str | None, fd: dict) -> dict:
    """What a reader must see next to any count from this file."""
    return {
        "faintest_reliable_v_bin": reliable,
        "false_detection_rate_per_pass": fd["passes"]["frac"],
        "false_detection_rate_per_track": fd["tracks"]["frac"],
        "caveats": [
            ("A pass counts as detected under the rule named in `rule`. On empty positions "
            "(offset control tracks) that rule fires at about the per-pass rate above."),
            ("A body counts as recovered if any one pass is; control tracks fire under the "
            "same rule at the per-track rate above (higher for TNOs, see "
            "false_detections.by_class)."),
            ("faintest_recovery is the faintest pass meeting the rules, not a credible limit "
            "when controls_fired > 0 (its own control tracks fired on the same frames)."),
            ("Counts at stricter S/N thresholds are in post_hoc_snr_thresholds; those "
            "thresholds were chosen after the controls were seen.")]}


def redecide(p: dict) -> dict:
    """A copy of a pass record decided under the pipeline's current rule (pass_outcome on
    its band S/N values), with the same position gate on the stored centroid."""
    out = pass_outcome([b["snr"] for b in p.get("bands") or [] if b.get("snr") is not None])
    c = p.get("centroid")
    near = c is not None and c["total"] <= POSITION_GATE_ARCSEC
    return {**p, "outcome": out, "candidate": out != "not detected",
            "detected": out == DETECTED, "recovered": out == DETECTED and near}


def apply_rule(recs: list[dict]) -> list[dict]:
    return [{**r, "passes": [redecide(p) for p in r["passes"]]} for r in recs]


def half_of(pdes: str) -> str:
    """Fixed split of the bodies into halves A and B (CRC-32 of the designation)."""
    return "AB"[zlib.crc32(pdes.encode()) % 2]


def calibration(recs: list[dict]) -> dict:
    """Control-pass false-detection rates per half of the bodies, old and new rule."""
    new = apply_rule(recs)

    def ctl(rs: list[dict], h: str) -> list[dict]:
        return [p for r in rs if r["variant"] != "real" and r["status"] == "ok"
                and half_of(r["body"]["pdes"]) == h for p in r["passes"]]

    halves = []
    for h in "AB":
        before, after = ctl(recs, h), ctl(new, h)
        halves.append({"half": h, "control_passes": _rate(sum(p["recovered"] for p in after),
                                                          len(after)),
                       "control_passes_before": _rate(sum(p["recovered"] for p in before),
                                                      len(before))})
    return {"split": "bodies by CRC-32 of the designation: even A, odd B",
            "criterion": ("rule family 'S/N >= 5 in the best band and S/N >= t in the second' "
                          "with t in {3, 4, 5}: the smallest t whose control-pass rate on "
                          "half A is at most 1%; half B reported as the check"),
            "chosen_t": 5.0, "halves": halves,
            "note": ("Half B was not blind: both halves were printed while the rule family "
                     "was explored. The single-band clause (S/N >= 50 with one band measurable) was added after the "
                     "data were seen, for a saturated bright pass (Hebe).")}


def report(recs: list[dict], failures: list[dict] | None = None,
           sample: list[dict] | None = None) -> dict:
    """The summary under the current rule, the v1-rule summary as `before`, and the split."""
    after = apply_rule(recs)
    old = summarise(recs, failures, sample)
    s = summarise(after, failures, sample)
    ctl = [p for r in after if r["variant"] != "real" and r["status"] == "ok"
           for p in r["passes"]]
    real = [p for r in after if r["variant"] == "real" and r["status"] == "ok"
            for p in r["passes"]]
    s["rule"] = ("S/N >= 5 in at least two control-corrected detector bands, or S/N >= 50 "
                 "in the only band measurable; a pass with one band at S/N >= 5 only is "
                 "'marginal'")
    s["marginal"] = {"control_passes": _rate(sum(p["outcome"] == MARGINAL for p in ctl),
                                             len(ctl)),
                     "real_passes": _rate(sum(p["outcome"] == MARGINAL for p in real),
                                          len(real))}
    s["post_hoc_snr_thresholds"] = old.pop("post_hoc_snr_thresholds")
    s["before"] = {"rule": BEFORE_RULE, **{k: old[k] for k in (
        "bodies", "by_class", "passes", "by_predicted_v", "faintest_reliable_bin",
        "faintest_recovery", "false_detections", "failures_by_cause")}}
    s["calibration"] = calibration(recs)
    return s


def _ci(c: list) -> str:
    return "-" if c[0] is None else f"{c[0]:.2f}-{c[1]:.2f}"


def _before_after(s: dict) -> list[str]:
    """Tables comparing the v1 rule (`before`) with the current one; empty without it."""
    b = s.get("before")
    if not b:
        return []
    old = {r["bin"]: r for r in b["by_predicted_v"]}
    rows = [f"| {r['bin']} | {r['n']} | {old[r['bin']]['k']} ({_ci(old[r['bin']]['ci95'])}) | "
            f"{r['k']} ({_ci(r['ci95'])}) | {r.get('n_marginal', 0)} |"
            for r in s["by_predicted_v"] if r["n"]]

    def rate(x: dict) -> str:
        return f"{x['k']} / {x['n']} ({_ci(x['ci95'])})"

    fa, fb = s["false_detections"], b["false_detections"]
    ctl = [f"| control passes | {rate(fb['passes'])} | {rate(fa['passes'])} |",
           f"| control tracks | {rate(fb['tracks'])} | {rate(fa['tracks'])} |",
           *[f"| {c} control tracks | {rate(fb['by_class'][c]['tracks'])} | "
             f"{rate(v['tracks'])} |" for c, v in fa["by_class"].items()],
           f"| real passes recovered | {rate(b['passes'])} | {rate(s['passes'])} |",
           (f"| bodies recovered | {b['bodies']['recovered']} / {b['bodies']['n']} | "
            f"{s['bodies']['recovered']} / {s['bodies']['n']} |"),
           (f"| faintest reliable V bin | {b['faintest_reliable_bin']} | "
            f"{s['faintest_reliable_bin']} |")]
    cal = [f"| {h['half']} | {rate(h['control_passes_before'])} | {rate(h['control_passes'])} |"
           for h in s["calibration"]["halves"]]
    return ["### Before and after the detection rule change", "",
            f"Before: {b['rule']}. After: {s['rule']}.", "",
            "| | before | after |", "|---|---|---|", *ctl, "",
            "Control passes by half of the bodies (" + s["calibration"]["split"] + "):", "",
            "| half | before | after |", "|---|---|---|", *cal, "",
            "Real passes recovered by predicted V:", "",
            "| V bin | covered passes | before | after | marginal (after) |",
            "|---|---|---|---|---|", *rows, ""]


def markdown(s: dict) -> str:
    fd = s["false_detections"]
    lines = ["| V bin | covered passes | detected | marginal | recovered | fraction | 95% CI |",
             "|---|---|---|---|---|---|---|"]
    for r in s["by_predicted_v"]:
        if r["n"]:
            lines.append(f"| {r['bin']} | {r['n']} | {r['n_detected']} | "
                         f"{r.get('n_marginal', 0)} | {r['k']} | {r['frac']:.2f} | "
                         f"{_ci(r['ci95'])} |")
    cls = ["| class | bodies | recovered | 95% CI |", "|---|---|---|---|"]
    cls += [f"| {k} | {v['n']} | {v['recovered']} | {_ci(v['ci95'])} |"
            for k, v in s["by_class"].items()]
    fails = [f"- {k}: {len(v)} ({', '.join(v)})" for k, v in s["failures_by_cause"].items()]
    a = s["astrometry"]
    return "\n".join([
        *_before_after(s),
        "### Recovery by predicted V (covered passes of the real track)", "", *lines, "",
        "### Bodies by class (recovered in at least one pass)", "", *cls, "",
        "### False detections (offset control tracks, same frames and pipeline)", "",
        (f"- control passes: {fd['passes']['k']} of {fd['passes']['n']} would count as "
        f"recovered (95% CI {_ci(fd['passes']['ci95'])}); without the position gate: "
        f"{fd['passes_snr_only']['k']} of {fd['passes_snr_only']['n']}"),
        (f"- control tracks: {fd['tracks']['k']} of {fd['tracks']['n']} "
        f"(95% CI {_ci(fd['tracks']['ci95'])})"),
        *[f"- {c}: passes {v['passes']['k']} of {v['passes']['n']} "
          f"({_ci(v['passes']['ci95'])}), tracks {v['tracks']['k']} of {v['tracks']['n']} "
          f"({_ci(v['tracks']['ci95'])})" for c, v in fd["by_class"].items()], "",
        "### Position of the detection relative to Horizons", "",
        (f"- body-centred stack centroid, recovered passes: median {a['centroid_median_arcsec']}"
        f" arcsec, 90th percentile {a['centroid_p90_arcsec']} arcsec (n = {a['centroid_n']})"),
        (f"- PSF-fit pass offset where its gates pass: median {a['psf_fit_median_arcsec']} "
        f"arcsec, 90th percentile {a['psf_fit_p90_arcsec']} arcsec (n = {a['psf_fit_n']})"), "",
        "### Bodies not recovered, by cause", "", *fails, "",
        ("### Post hoc, under the v1 rule: stricter best-band S/N thresholds (chosen after the "
         "controls were seen)"), "",
        ("| S/N min | control passes counted | real passes recovered | bodies recovered |"
        " faintest reliable V bin |"),
        "|---|---|---|---|---|",
        *[f"| {t['snr_min']:g} | {t['control_passes']['k']} / {t['control_passes']['n']} "
          f"({_ci(t['control_passes']['ci95'])}) | {t['real_passes']['k']} / "
          f"{t['real_passes']['n']} | {t['real_bodies']['k']} / {t['real_bodies']['n']} | "
          f"{t['faintest_reliable_bin']} |"
          for t in s["post_hoc_snr_thresholds"]], ""])


def load(root: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(root.glob("*/*.json"))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", type=Path)
    ap.add_argument("--failures", type=Path)
    ap.add_argument("--sample", type=Path, default=Path(__file__).with_name("sample.json"))
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args(argv)
    fails = json.loads(a.failures.read_text()) if a.failures else []
    s = report(load(a.results), fails, json.loads(a.sample.read_text())["bodies"])
    text = json.dumps(s, indent=1, allow_nan=False) + "\n"
    (a.json.write_text(text) if a.json else sys.stdout.write(text))
    md = markdown(s)
    (a.md.write_text(md) if a.md else sys.stdout.write(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
