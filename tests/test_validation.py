"""The validation scoreboard: pass rules, manifest facts, and the written report."""

import json
from pathlib import Path

import pytest

from pxs.validation.report import build_report, write_report
from pxs.validation.rules import (
    FAIL,
    NOT_APPLICABLE,
    PASS,
    REFUSED,
    WEAK_TEST_FACTOR,
    all_frames_note,
    motion_check,
    parse_published,
    second_reference,
    type_check,
)
from pxs.validation.stats import (
    declined_reason,
    degraded_info,
    epoch_key,
    frame_stats,
    motion_missing_reason,
    residual_info,
)

ROOT = Path(__file__).resolve().parents[1]


def _meas(ra, dec, err=6.0):
    return {"pmra_masyr": ra, "pmdec_masyr": dec, "err_pmra_masyr": err, "err_pmdec_masyr": err,
            "baseline_years": 16.0, "n_detections": 20}


def test_motion_passes_within_three_sigma() -> None:
    r = motion_check(_meas(1010.0, -500.0), {"pmra_masyr": 1000.0, "pmdec_masyr": -500.0})
    assert r["verdict"] == PASS and r["sigma"]["max"] == pytest.approx(10 / 6)


def test_epsilon_indi_declination_fails_despite_small_percentage() -> None:
    r = motion_check(_meas(3991.1, -2510.18, 5.95), {"pmra_masyr": 3981.977, "pmdec_masyr": -2466.832})
    assert r["verdict"] == FAIL
    assert r["sigma"]["pmdec"] == pytest.approx(7.285, abs=0.01)
    assert abs(r["diff"]["pmdec_pct"]) < 2  # a 2% rule would have hidden this


def test_a_catalogue_motion_below_three_errors_is_a_weak_test() -> None:
    assert WEAK_TEST_FACTOR == 3.0
    slow = motion_check(_meas(10.0, 20.0, 10.27), {"pmra_masyr": 5.0, "pmdec_masyr": 27.0})
    assert slow["verdict"] == PASS and slow["weak_test"] is True
    fast = motion_check(_meas(1010.0, -500.0), {"pmra_masyr": 1000.0, "pmdec_masyr": -500.0})
    assert fast["weak_test"] is False
    # Just above the factor: 3 x 6 = 18 mas/yr against a catalogue motion of 18.1.
    assert motion_check(_meas(0.0, 18.1), {"pmra_masyr": 0.0, "pmdec_masyr": 18.1})["weak_test"] is False
    assert motion_check(None, {"pmra_masyr": 1.0, "pmdec_masyr": 1.0})["weak_test"] is None


def test_the_gallery_weak_tests_are_the_two_slow_stars() -> None:
    report = json.loads((ROOT / "web" / "data" / "validation.json").read_text())
    weak = sorted(t["slug"] for t in report["targets"] if t["motion"]["weak_test"])
    assert weak == ["r-draconis", "rw-aurigae"]
    assert "weak_test" in report["thresholds"]


def test_motion_without_error_is_not_applicable() -> None:
    m = {"pmra_masyr": 1.0, "pmdec_masyr": 1.0}
    assert motion_check(m, {"pmra_masyr": 1.0, "pmdec_masyr": 1.0})["verdict"] == NOT_APPLICABLE


@pytest.mark.parametrize("text,expected", [
    ("T1-1.5 + T6 (unresolved pair)", [(11.0, 11.5), (16.0, 16.0)]),
    ("Y4 (adopted estimate)", [(24.0, 24.0)]),
    ("M4 star", [(-6.0, -6.0)]),
    ("d/sdL9", [(9.0, 9.0)]),
    ("sdT3", [(13.0, 13.0)]),
])
def test_published_types_parse(text, expected) -> None:
    assert parse_published(text) == expected


def test_unparsable_type_is_none() -> None:
    assert parse_published("K1-K5 young star (T Tauri)") is None


def _match(lo, hi, best, **kw):
    return {"best": {"type": best}, "type_range": [lo, hi], **kw}


def test_type_range_contains_published() -> None:
    assert type_check(_match("T7", "T9", "T8"), "T8", True, None)["verdict"] == PASS
    assert type_check(_match("T7", "T9", "T8"), "L9", True, None)["verdict"] == FAIL


def test_an_uncertain_fit_is_never_scored_as_a_type() -> None:
    r = type_check(_match("T7", "T9", "T8", **{"class": "uncertain"}), "T8", True, None)
    assert r["verdict"] == REFUSED and "unclassified" in r["reason"]


def test_pair_published_uses_any_component_and_range_must_hold_published_span() -> None:
    m = _match("T1", "T3", "T2", pair={"types": ["T2", "T6"]})
    assert type_check(m, "T1-1.5 + T6 (unresolved pair)", True, None)["verdict"] == PASS
    assert type_check(_match("T2", "T3", "T2"), "T1-1.5", True, None)["verdict"] == FAIL


def test_open_ends_are_unbounded() -> None:
    m = _match("Y0", "Y1", "Y1", range_open_cold=True)
    assert type_check(m, "Y4", True, None)["verdict"] == PASS


def test_refused_needs_a_spectrum_otherwise_not_applicable() -> None:
    assert type_check(None, "Y4", True, "blend")["verdict"] == REFUSED
    r = type_check(None, "M4 star", False, "no spectrum to judge")
    assert r["verdict"] == NOT_APPLICABLE and r["reason"] == "no spectrum to judge"


def test_epoch_key_pairs_missions_by_visit() -> None:
    assert epoch_key("wise-w1-2010a") == epoch_key("spx-b2-2010a") == "2010a"


def _manifest(frames, warnings=(), degraded=False):
    return {"frames": frames, "warnings": list(warnings), "degraded": degraded,
            "fov_arcsec": 240.0, "size_px": 240}


def test_frame_stats_counts_and_gap_warning() -> None:
    gap = "The IRSA search for WISE frames from 2013-2024 (NEOWISE) failed, so those are missing."
    m = _manifest([
        {"id": "wise-w1-2010a", "mission": "WISE", "date": "2010-04-01T00:00:00Z"},
        {"id": "wise-w2-2010a", "mission": "WISE", "date": "2010-04-01T00:00:00Z"},
        {"id": "spx-b1-2025a", "mission": "SPHEREx", "date": "2025-05-01T00:00:00Z"},
    ], [gap, "something else is missing"])
    s = frame_stats(m)
    assert s["wise"] == {"frames": 2, "epochs": 1, "first_year": 2010, "last_year": 2010}
    assert s["spherex"] == {"frames": 1, "epochs": 1}
    assert s["gaps"] == [gap]


def test_residual_picks_largest_and_converts_units() -> None:
    m = _manifest([
        {"id": "a", "mission": "WISE", "centroid_px": [10, 10], "predicted_px": [10, 11],
         "native_pixscale_arcsec": 2.75},
        {"id": "b", "mission": "SPHEREx", "centroid_px": [13, 14], "predicted_px": [10, 10],
         "native_pixscale_arcsec": 5.0},
        {"id": "c", "mission": "WISE", "centroid_px": None, "predicted_px": [1, 1]},
    ])
    r = residual_info(m)
    assert (r["frame_id"], r["max_px"], r["undetected"]) == ("b", 5.0, 1)
    assert r["max_native_px"] == pytest.approx(1.0)
    assert residual_info(_manifest([]))["max_px"] is None


def test_degraded_reasons_come_from_warnings() -> None:
    d = degraded_info(_manifest([], ["CatWISE2020 sources could not be fetched.", "saturated"], True))
    assert d == {"flag": True, "reasons": ["CatWISE2020 sources could not be fetched."]}


def test_build_report_summary_and_epsilon_note() -> None:
    entry = {"slug": "epsilon-indi-b", "name": "E", "known_type": "T1-1.5 + T6"}
    man = {**_manifest([]), "target": {}, "measured_motion": _meas(3991.1, -2510.18, 5.95),
           "match": _match("T1", "T3", "T2"), "spectra": [{}], "generated": "2026-01-01T00:00:00Z"}
    pub = {"slug": "epsilon-indi-b", "pmra_masyr": 3981.977, "pmdec_masyr": -2466.832,
           "pm_source": "Gaia DR3", "known_type": "T1-1.5 + T6 (unresolved pair)"}
    rep = build_report({"targets": [entry]}, {"epsilon-indi-b": man}, [pub])
    assert rep["summary"]["motion"] == {"passed": 0, "failed": 1, "total": 1, "refused": 0, "not_applicable": 0}
    assert rep["summary"]["type"]["passed"] == 1
    assert "11 years" in rep["targets"][0]["motion"]["note"]
    assert rep["built"] == "2026-01-01T00:00:00Z"


def test_write_report_is_deterministic_and_matches_the_gallery(tmp_path: Path) -> None:
    gallery = ROOT / "web" / "gallery"
    targets = ROOT / "data" / "targets.json"
    a = write_report(gallery, targets, tmp_path / "a.json")
    write_report(gallery, targets, tmp_path / "b.json")
    assert (tmp_path / "a.json").read_text() == (tmp_path / "b.json").read_text()
    assert json.loads((tmp_path / "a.json").read_text()) == a
    entries = json.loads((gallery / "index.json").read_text())["targets"]
    stars = [e for e in entries if e.get("group") != "solar-system"]  # body views are left out
    assert a["summary"]["targets"] == len(stars)


# --- targets with missing data: not applicable, never a crash --------------------------------

CAT = {"pmra_masyr": 7.0, "pmdec_masyr": -980.0}


def test_no_measured_motion_is_not_applicable_with_the_manifest_reason() -> None:
    r = motion_check(None, CAT, "The target was not detected in any frame, so no motion was measured.")
    assert r["verdict"] == NOT_APPLICABLE and r["sigma"] is None
    assert "not detected in any frame" in r["reason"]
    assert r["catalogue"]["pmra"] == 7.0 and r["measured"]["pmra"] is None
    assert r["diff"]["pmra"] is None and r["n_detections"] is None


def test_no_measured_motion_without_a_stated_reason_says_fewer_than_two_detections() -> None:
    assert "fewer than two detections" in motion_check(None, CAT)["reason"].lower()


def test_no_catalogue_motion_is_not_applicable_but_keeps_the_measured_value() -> None:
    r = motion_check(_meas(5.0, -2.0), {"pmra_masyr": None, "pmdec_masyr": None})
    assert r["verdict"] == NOT_APPLICABLE and "no published proper motion" in r["reason"].lower()
    assert r["measured"]["pmra"] == 5.0 and r["catalogue"]["pmra"] is None and r["diff"]["pmra"] is None


def test_class_agreement_passes_for_a_published_star() -> None:
    m = {"best": {"type": "dust + star"}, "type_range": None, "class": "not a brown dwarf"}
    r = type_check(m, "K1-K5 young star (T Tauri)", True, None)
    assert r["verdict"] == PASS and "not a brown dwarf" in r["reason"]
    assert type_check(m, "M4.5-M6 giant (Mira variable)", True, None)["verdict"] == PASS


def test_not_a_brown_dwarf_against_a_published_brown_dwarf_fails() -> None:
    m = {"best": {"type": "dust + star"}, "type_range": None, "class": "not a brown dwarf"}
    assert type_check(m, "d/sdL9", True, None)["verdict"] == FAIL


def test_not_a_brown_dwarf_with_no_published_type_is_not_applicable() -> None:
    m = {"best": {"type": "dust + star"}, "type_range": None, "class": "not a brown dwarf"}
    r = type_check(m, None, True, None)
    assert r["verdict"] == NOT_APPLICABLE and r["best"] == "dust + star"


def test_no_published_type_shows_the_tool_result() -> None:
    r = type_check(_match("T7", "T9", "T8"), None, True, None)
    assert r["verdict"] == NOT_APPLICABLE and r["best"] == "T8" and r["range"] == ["T7", "T9"]


def test_summary_counts_add_up(tmp_path: Path) -> None:
    rep = write_report(ROOT / "web" / "gallery", ROOT / "data" / "targets.json", tmp_path / "v.json")
    s = rep["summary"]
    for check in ("motion", "type"):
        c = s[check]
        faint = c.get("faint", {})  # types of faint spectra are counted apart
        apart = faint.get("passed", 0) + faint.get("failed", 0)
        assert (c["passed"] + c["failed"] + c["refused"] + c["not_applicable"] + apart
                == s["targets"])
        assert c["total"] == c["passed"] + c["failed"]
    assert all(t["group"] for t in rep["targets"])


def test_too_little_spectrum_is_a_stated_refusal_reason() -> None:
    w = "SPHEREx detects the object at only 12 wavelengths (1.7 to 4.2 um), which is too little of the spectrum to classify it."
    assert declined_reason({"warnings": [w]}) == w


def test_a_provisional_type_is_still_scored_and_flagged() -> None:
    m = {**_match("T7", "T9", "T8"), "provisional": "treat the type as provisional"}
    r = type_check(m, "T8", True, None)
    assert r["verdict"] == PASS and r["provisional"] == "treat the type as provisional"
    assert type_check(_match("T7", "T9", "T8"), "T8", True, None)["provisional"] is None
    assert type_check(None, "T8", True, "x")["provisional"] is None


def test_summary_counts_provisional_types() -> None:
    from pxs.validation.report import summarise

    def row(prov):
        return {"motion": {"verdict": PASS}, "type": {"verdict": PASS, "provisional": prov},
                "degraded": {"flag": False}}
    assert summarise([row("x"), row(None)])["type"]["provisional"] == 1


def test_the_two_kinds_of_provisional_are_told_apart() -> None:
    m = {**_match("T7", "T9", "T8"), "provisional": "treat the type as provisional"}
    assert type_check(m, "T8", True, None)["provisional_kind"] == "neighbour"  # older manifest
    faint = {**m, "provisional_kind": "faint"}
    assert type_check(faint, "T8", True, None)["provisional_kind"] == "faint"
    assert type_check(_match("T7", "T9", "T8"), "T8", True, None)["provisional_kind"] is None
    assert type_check(None, "T8", True, "x")["provisional_kind"] is None


def test_a_faint_type_is_counted_apart_from_the_other_types() -> None:
    from pxs.validation.report import summarise

    def row(verdict, kind=None, open_cold=False):
        return {"motion": {"verdict": PASS}, "degraded": {"flag": False},
                "type": {"verdict": verdict, "provisional": "x" if kind else None,
                         "provisional_kind": kind, "range_open_cold": open_cold}}

    rows = [row(PASS), row(PASS, "neighbour"), row(PASS, "faint", open_cold=True),
            row(FAIL, "faint"), row(REFUSED)]
    t = summarise(rows)["type"]
    assert (t["passed"], t["failed"], t["total"], t["provisional"], t["refused"]) == (2, 0, 2, 1, 1)
    assert t["faint"] == {"passed": 1, "failed": 1, "open_ended": 1}
    assert summarise([row(PASS)])["type"]["faint"] == {"passed": 0, "failed": 0, "open_ended": 0}


def test_a_missing_motion_is_explained_in_the_views_own_words() -> None:
    blended = "3 detections are left out of the motion fit because a catalogued source of similar brightness lies within the area the position is fitted over."
    frames = [{"centroid_px": [1, 1]}] * 3
    assert motion_missing_reason({"warnings": ["x", blended], "frames": frames}) == blended
    assert motion_missing_reason({"warnings": ["The target was not detected in any frame."], "frames": []}).startswith("The target was not detected")
    assert motion_missing_reason({"warnings": [], "frames": frames[:1]}).startswith("Only 1 detection,")
    assert "manifest" not in motion_missing_reason({"warnings": [], "frames": frames})


def test_a_refusal_without_a_reason_says_so_plainly() -> None:
    assert "manifest" not in type_check(None, "K1", True, None)["reason"]
    assert type_check(None, "K1", False, None)["reason"] == "There is no SPHEREx spectrum to classify."


# --- a motion fitted on all images at once, and a second reference -------------------------

CHEN = {"pmra_masyr": 3987.41, "pmdec_masyr": -2505.35, "source": "Chen et al. 2022",
        "caveat": "Expected only if the light divides as the mass does."}


def _all_frames(ra, dec, err=38.9):
    return {**_meas(ra, dec, err), "n_detections": 0, "n_frames": 23, "method": "all_frames"}


def test_an_all_frames_motion_says_it_has_no_detections() -> None:
    row = motion_check(_all_frames(17.45, -892.03), {"pmra_masyr": 7.0, "pmdec_masyr": -980.0})
    assert row["verdict"] == PASS and row["method"] == "all_frames"
    assert row["n_frames"] == 23 and row["n_detections"] == 0
    note = all_frames_note(row)
    assert "no detections" in note and "all 23 W2 images at once" in note
    assert all_frames_note(motion_check(_meas(1.0, 1.0), {"pmra_masyr": 1.0, "pmdec_masyr": 1.0})) is None


def test_the_report_carries_the_all_frames_note_on_a_pass_and_on_a_fail() -> None:
    entry = {"slug": "x", "name": "X"}
    pub = {"slug": "x", "pmra_masyr": 7.0, "pmdec_masyr": -980.0}
    for dec, verdict in ((-892.03, PASS), (-700.0, FAIL)):
        man = {**_manifest([]), "target": {}, "measured_motion": _all_frames(17.45, dec)}
        m = build_report({"targets": [entry]}, {"x": man}, [pub])["targets"][0]["motion"]
        assert m["verdict"] == verdict and "all 23 W2 images at once" in m["note"]
    plain = {**_manifest([]), "target": {}, "measured_motion": _meas(8.0, -975.0)}
    m = build_report({"targets": [entry]}, {"x": plain}, [pub])["targets"][0]["motion"]
    assert m["note"] is None and m["method"] is None and m["second_reference"] is None


def test_a_second_reference_is_shown_beside_the_verdict_and_never_changes_it() -> None:
    entry = {"slug": "epsilon-indi-b", "name": "E"}
    man = {**_manifest([]), "target": {}, "measured_motion": _meas(3991.18, -2509.2, 5.95)}
    pub = {"slug": "epsilon-indi-b", "pmra_masyr": 3981.977, "pmdec_masyr": -2466.832,
           "pm_source": "Gaia DR3", "pm_second_reference": CHEN}
    m = build_report({"targets": [entry]}, {"epsilon-indi-b": man}, [pub])["targets"][0]["motion"]
    assert m["verdict"] == FAIL and m["sigma"]["pmdec"] == pytest.approx(7.12, abs=0.01)
    ref = m["second_reference"]
    assert ref["sigma"]["pmra"] == pytest.approx(0.63, abs=0.01)
    assert ref["sigma"]["pmdec"] == pytest.approx(0.65, abs=0.01)
    assert "Chen et al. 2022" in ref["text"] and "light divides as the mass" in ref["text"]
    assert second_reference(None, CHEN) is None and second_reference(_meas(1.0, 1.0), None) is None
