"""Statistics of the body-recovery campaign from synthetic result records (offline)."""

from __future__ import annotations

import json

import pytest
from solarsystem_validation.analyse import (
    body_outcome,
    clopper_pearson,
    faintest_reliable,
    false_detections,
    markdown,
    recovery_table,
    summarise,
)


def _pass(v: float, recovered: bool, detected: bool | None = None, n_sat: int = 0,
          b: float = 40.0, off: float | None = 2.0) -> dict:
    det = recovered if detected is None else detected
    return {"date_start": "2025-06-01", "date_end": "2025-06-05", "n_frames": 100,
            "n_measured": 100, "n_usable": 90, "n_saturated": n_sat, "vmag": v,
            "gal_b": b, "best_band": "spx-b1", "best_snr": 9.0 if det else 1.0,
            "detected": det, "recovered": recovered,
            "centroid": {"east": off, "north": 0.0, "total": off} if det else None,
            "recentre": None}


def _rec(pdes: str, variant: str, passes: list[dict], status: str = "ok", cls: str = "MBA",
         error_kind: str = "", n_visits: int = 100) -> dict:
    return {"body": {"pdes": pdes, "name": pdes, "cls": cls, "H": 12.0}, "variant": variant,
            "status": status, "error": {"kind": error_kind, "type": "X", "message": "m"}
            if status != "ok" else None, "track": {"n_visits": n_visits}, "passes": passes,
            "skipped": [], "wall_s": 10.0}


def test_clopper_pearson_known_values():
    lo, hi = clopper_pearson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.3085, abs=1e-3)
    lo, hi = clopper_pearson(10, 10)
    assert lo == pytest.approx(0.6915, abs=1e-3) and hi == 1.0
    lo, hi = clopper_pearson(5, 10)
    assert lo == pytest.approx(0.187, abs=2e-3) and hi == pytest.approx(0.813, abs=2e-3)
    assert clopper_pearson(0, 0) == (None, None)


def test_recovery_table_bins_by_predicted_v():
    passes = [_pass(15.5, True), _pass(15.2, True), _pass(19.4, False), _pass(19.6, True)]
    rows = {r["bin"]: r for r in recovery_table(passes, [15.0, 16.0, 19.0, 20.0])}
    assert rows["15-16"]["n"] == 2 and rows["15-16"]["k"] == 2
    assert rows["19-20"]["n"] == 2 and rows["19-20"]["k"] == 1
    assert rows["16-19"]["n"] == 0


def test_faintest_reliable_needs_lower_bound_of_half():
    rows = [{"bin": "15-16", "lo_v": 15.0, "n": 10, "k": 10, "ci95": [0.69, 1.0]},
            {"bin": "16-17", "lo_v": 16.0, "n": 10, "k": 8, "ci95": [0.44, 0.97]},
            {"bin": "17-18", "lo_v": 17.0, "n": 3, "k": 1, "ci95": [0.01, 0.9]}]
    assert faintest_reliable(rows) == "15-16"
    assert faintest_reliable(rows[1:]) is None


def test_body_outcomes_by_cause():
    assert body_outcome(_rec("1", "real", [_pass(15, True)])) == "recovered"
    assert body_outcome(_rec("1", "real", [], status="error", error_kind="horizons")) == \
        "Horizons failure"
    assert body_outcome(_rec("1", "real", [], status="error", error_kind="bug")) == \
        "pipeline error (bug)"
    assert body_outcome(_rec("1", "real", [], status="error", error_kind="timeout")) == \
        "timeout"
    assert body_outcome(_rec("1", "real", [], n_visits=0)) == "no coverage"
    assert body_outcome(_rec("1", "real", [])) == "too few frames per pass"
    sat = _pass(9.0, False, n_sat=80)
    assert body_outcome(_rec("1", "real", [sat])) == "saturated"
    off = _pass(15.0, False, detected=True, off=30.0)
    assert body_outcome(_rec("1", "real", [off])) == "detected off position"
    assert body_outcome(_rec("1", "real", [_pass(15.0, False, b=3.0)])) == \
        "not detected, crowded field (|b| < 10 deg)"
    assert body_outcome(_rec("1", "real", [_pass(21.0, False)])) == "not detected"


def test_false_detections_count_passes_and_tracks():
    recs = [_rec("1", "off_ra", [_pass(15, False), _pass(15, True)]),
            _rec("1", "off_dec", [_pass(15, False)]),
            _rec("2", "off_ra", [], n_visits=0)]
    fd = false_detections(recs)
    assert fd["passes"]["n"] == 3 and fd["passes"]["k"] == 1
    assert fd["tracks"]["n"] == 2 and fd["tracks"]["k"] == 1  # tracks with >= 1 covered pass


def test_summarise_and_markdown_are_consistent_and_json():
    recs = [_rec("1", "real", [_pass(15.5, True)]), _rec("1", "off_ra", [_pass(15.5, False)]),
            _rec("2", "real", [_pass(20.5, False)], cls="TNO"),
            _rec("3", "real", [], status="error", error_kind="horizons")]
    s = summarise(recs)
    json.dumps(s, allow_nan=False)
    assert s["bodies"]["n"] == 3 and s["bodies"]["recovered"] == 1
    assert s["failures_by_cause"]["Horizons failure"] == ["3"]
    assert s["false_detections"]["passes"]["k"] == 0
    one = next(o for o in s["outcomes"] if o["pdes"] == "1")
    assert one["n_passes"] == 1 and one["n_recovered"] == 1 and one["vmag_min"] == 15.5
    md = markdown(s)
    assert "| V bin |" in md and "False detections" in md


def test_threshold_scan_counts_only_passes_above_the_threshold():
    from solarsystem_validation.analyse import threshold_scan

    weak, strong = _pass(15.0, True), _pass(15.0, True)
    weak["best_snr"], strong["best_snr"] = 6.0, 20.0
    recs = [_rec("1", "real", [weak, strong]), _rec("1", "off_ra", [dict(weak)])]
    five, ten = threshold_scan(recs, [5.0, 10.0])
    assert five["control_passes"]["k"] == 1 and five["real_passes"]["k"] == 2
    assert ten["control_passes"]["k"] == 0 and ten["real_passes"]["k"] == 1
    assert ten["real_bodies"]["k"] == 1 and ten["real_bodies"]["n"] == 1


def test_false_detections_by_class_and_controls_fired_per_body():
    from solarsystem_validation.analyse import controls_fired

    recs = [_rec("1", "off_ra", [_pass(20, True)], cls="TNO"),
            _rec("1", "off_dec", [_pass(20, False)], cls="TNO"),
            _rec("2", "off_ra", [_pass(15, False)], cls="MBA")]
    by = false_detections(recs)["by_class"]
    assert by["TNO"]["tracks"]["k"] == 1 and by["TNO"]["tracks"]["n"] == 2
    assert by["MBA"]["passes"]["k"] == 0
    assert controls_fired(recs) == {"1": 1, "2": 0}
    s = summarise([*recs, _rec("1", "real", [_pass(25.0, True)], cls="TNO")])
    assert s["faintest_recovery"]["controls_fired"] == 1
    assert s["headline"]["false_detection_rate_per_pass"] == pytest.approx(1 / 3, abs=1e-3)


def _banded(v: float, snrs: list[float | None], off: float = 2.0) -> dict:
    """A v1-style record pass (detected under the old one-band rule) with band S/N values."""
    p = _pass(v, True, off=off)
    p["bands"] = [{"band": f"spx-b{i + 1}", "snr": s} for i, s in enumerate(snrs)]
    p["best_snr"] = max(s for s in snrs if s is not None)
    p["recovered"] = off <= 12.3
    return p


def test_redecide_applies_the_two_band_rule_and_keeps_the_position_gate():
    from solarsystem_validation.analyse import redecide

    one = redecide(_banded(20.0, [9.0, 1.0, None]))
    assert one["outcome"] == "marginal" and not one["detected"] and not one["recovered"]
    two = redecide(_banded(20.0, [9.0, 5.5, 0.0]))
    assert two["outcome"] == "detected" and two["detected"] and two["recovered"]
    far = redecide(_banded(20.0, [9.0, 5.5], off=30.0))
    assert far["detected"] and not far["recovered"]
    quiet = redecide({**_pass(20.0, False), "bands": [{"snr": 1.0}]})
    assert quiet["outcome"] == "not detected" and not quiet["recovered"]


def test_marginal_only_body_has_its_own_cause_and_bin_count():
    from solarsystem_validation.analyse import MARGINAL_CAUSE, redecide

    p = redecide(_banded(20.5, [7.0, 0.0]))
    assert body_outcome(_rec("1", "real", [p])) == MARGINAL_CAUSE
    row = next(r for r in recovery_table([p]) if r["bin"] == "20-21")
    assert row["n_marginal"] == 1 and row["k"] == 0


def test_report_gives_before_after_and_a_by_body_calibration_split():
    from solarsystem_validation.analyse import report

    recs = [_rec("1", "real", [_banded(15.0, [30.0, 20.0])]),
            _rec("1", "off_ra", [_banded(15.0, [8.0, 0.0])]),
            _rec("2", "real", [_banded(20.5, [6.0, 1.0])]),
            _rec("2", "off_dec", [_banded(20.5, [6.0, 6.0])])]
    s = report(recs)
    json.dumps(s, allow_nan=False)
    assert s["false_detections"]["passes"]["k"] == 1  # only the two-band control pass
    assert s["before"]["false_detections"]["passes"]["k"] == 2
    assert s["before"]["passes"]["k"] == 2 and s["passes"]["k"] == 1
    cal = s["calibration"]
    assert {h["half"] for h in cal["halves"]} == {"A", "B"}
    assert sum(h["control_passes"]["n"] for h in cal["halves"]) == 2
    md = markdown(s)
    assert "| V bin |" in md and "Before and after" in md


def test_position_gate_matches_measure():
    from solarsystem_validation import analyse, measure

    assert analyse.POSITION_GATE_ARCSEC == measure.POSITION_GATE_ARCSEC
