"""How pxs.spectra matches a spectrum that fails the count gate, and what the gate then
does with it: a real T8 made fainter, an RW Aurigae-like spectrum with almost no points."""

import json
from pathlib import Path

import numpy as np
from build_fakes import FakeSpecPoint

from pxs import spectra
from pxs.typegate import FAINT_HALF_WIDTH, FAINT_MIN_SIGMA, FAINT_NOTE, faint_reason, vet
from pxs.typing import load_templates

FIXTURE = Path(__file__).parents[1] / "fixtures" / "spectra" / "2mass-0415-0935.json"
ARRAY_EDGES_UM = (1.11, 1.63, 2.42, 3.82, 4.42)


def _passes(divide: float, seed: int, n_passes: int = 2):
    """2MASS 0415 (T8) `divide` times fainter, seen in `n_passes` passes with faint-field noise."""
    fix = json.loads(FIXTURE.read_text())
    wl, flux = np.array(fix["wl_um"]), np.array(fix["flux_mjy"]) / divide
    sigma = np.where(wl > 3.8, 0.11, 0.03) * np.sqrt(n_passes)
    rng = np.random.default_rng(seed)
    return [[FakeSpecPoint(float(w), float(w) / 40.0, float(f + rng.normal(0.0, s)), float(s),
                           1 + int(np.searchsorted(ARRAY_EDGES_UM, w)), False, 60700.0 + 200 * k)
             for w, f, s in zip(wl, flux, sigma)] for k in range(n_passes)]


def _half_widths(match: dict) -> tuple[int, int]:
    labels = list(load_templates())
    lo, hi = (labels.index(t) for t in match["type_range"])
    best = min((c for c in match["candidates"] if c["family"] == "brown dwarf"),
               key=lambda c: c["chi2"])
    return labels.index(best["type"]) - lo, hi - labels.index(best["type"])


def test_a_faint_spectrum_is_matched_with_the_wide_range() -> None:
    out = spectra.build_all(_passes(8.0, seed=1))
    combined = out.spectra[-1]
    assert faint_reason(combined) is not None  # fails the count
    m = out.match
    assert m["spectrum_id"] == "spx-all" and m["detection_sigma"] >= FAINT_MIN_SIGMA
    warm, cold = _half_widths(m)
    last = list(load_templates())[-1]
    assert warm >= FAINT_HALF_WIDTH and (cold >= FAINT_HALF_WIDTH or m["type_range"][1] == last)


def test_a_bright_spectrum_keeps_the_usual_range() -> None:
    m = spectra.build_all(_passes(1.0, seed=1)).match
    assert m["type_range"] == ["T7", "T9"]


def test_the_gate_types_a_decisive_faint_fit_as_provisional_or_says_why_not() -> None:
    typed = 0
    for seed in range(6):
        out = spectra.build_all(_passes(8.0, seed=seed))
        match, notes = vet(out.match, out.spectra, blended=False)
        if match is None:
            assert len(notes) == 1 and "not classified" in notes[0]
            continue
        typed += 1
        assert match["provisional"] == FAINT_NOTE and notes == [FAINT_NOTE]
        assert match["class"] == "brown dwarf"
        labels = list(load_templates())
        lo, hi = (labels.index(t) for t in match["type_range"])
        assert lo <= labels.index("T8") <= hi
    assert typed >= 1


def test_one_faint_pass_alone_is_matched_the_same_way() -> None:
    out = spectra.build_all(_passes(8.0, seed=1, n_passes=1))
    assert [s["id"] for s in out.spectra] == ["spx-2025a"]
    assert sum(_half_widths(out.match)) >= 2 * FAINT_HALF_WIDTH - 1


def test_cwise_1055_real_spectrum_is_a_provisional_cold_type() -> None:
    # The gallery's combined spectrum of CWISE J1055+5443 (published Y0 peculiar): 7 points
    # at S/N >= 3, the fit as a whole at 12.9 sigma with the CO band seen.
    fix = json.loads((FIXTURE.parent / "cwise-1055-5443.json").read_text())
    spec = {"id": "spx-all", "points": fix["points"]}
    assert "only 7 wavelengths" in faint_reason(spec)
    fit = spectra._own_match(spec)
    match, notes = vet(fit, [spec], blended=False)
    assert notes == [FAINT_NOTE] and match["provisional"] == FAINT_NOTE
    assert match["class"] == "brown dwarf" and match["detection_sigma"] == 12.9
    assert match["type_range"] == ["T8", "Y1"] and match["range_open_cold"]
    assert vet(fit, [spec], blended=False, seen=False)[0] is None


def test_a_spectrum_with_almost_no_usable_points_has_no_match_and_a_reason() -> None:
    def point(w, flagged, mjd):
        return FakeSpecPoint(w, w / 40.0, None if flagged else 150.0, None if flagged else 1.0,
                             1, flagged, mjd)

    passes = [[point(0.75 + 0.05 * i, i >= 8, 60700.0 + 200 * k) for i in range(80)]
              for k in range(2)]  # usable only at 0.75-1.10 um: 2 points inside the templates
    out = spectra.build_all(passes)
    assert out.match is None
    match, notes = vet(out.match, out.spectra, blended=False)
    assert match is None and len(notes) == 1
    assert notes[0].startswith("The spectrum is not classified because only 2 of its points")
