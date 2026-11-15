"""Sanity outcomes on real SPHEREx spectra (fixtures: all passes binned, see each file)."""

import json
from pathlib import Path

import pytest

from pxs.typing import match_spectrum

FIXTURES = Path(__file__).parent / "fixtures" / "spectra"


def run(slug):
    fix = json.loads((FIXTURES / f"{slug}.json").read_text())
    return match_spectrum(fix["wl_um"], fix["flux_mjy"], fix["err_mjy"])


def idx(label):
    return 10 * "MLTY".index(label[0]) + int(label[1])


def test_2mass_0415_is_a_t8():
    r = run("2mass-0415-0935")
    assert r["class"] == "brown dwarf" and r["confidence"] == "high"
    assert r["best"]["type"] == "T8"
    lo, hi = r["type_range"]
    assert idx(lo) <= idx("T8") <= idx(hi)
    assert r["pair"] is None
    assert "CH4 3.3 um" in r["bands_detected"]


def test_epsilon_indi_b_is_flagged_as_a_pair_never_a_single_narrow_type():
    r = run("epsilon-indi-b")
    assert r["class"] == "brown dwarf"
    assert r["type_range"] != ["T2", "T2"]
    lo, hi = r["type_range"]
    assert idx(hi) - idx(lo) >= 2
    t1, t2 = r["pair"]["types"]
    assert idx("L9") <= idx(t1) <= idx("T3") and idx("T5") <= idx(t2) <= idx("T7")
    assert r["verdict"].startswith("Fits better as two brown dwarfs blended together")
    assert r["pair"]["model"] == f"{t1} + {t2}" and len(r["models"][r["pair"]["model"]]) == len(r["models"][r["best"]["type"]])


def test_wise_0855_is_never_a_confident_mid_t():
    r = run("wise-0855-0714")
    assert r["class"] != "brown dwarf" or "Y1 or colder" in r["verdict"]
    assert r["confidence"] == "low"
    if r["type_range"] is not None:
        assert r["range_open_cold"]
    assert not (r["best"]["type"][0] == "T" and 2 <= int(r["best"]["type"][1]) <= 7)


@pytest.mark.parametrize("slug", ["2mass-0415-0935", "epsilon-indi-b", "wise-0855-0714"])
def test_fixture_is_well_formed(slug):
    fix = json.loads((FIXTURES / f"{slug}.json").read_text())
    n = len(fix["wl_um"])
    assert n == len(fix["flux_mjy"]) == len(fix["err_mjy"]) > 50
    assert fix["published_type"]
