"""Campaign summary for the site: Wilson intervals, bins, peak counts, determinism (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pxs.movers.summary import coarse_bins, render, wilson

REPORT = {
    "train_fields": ["B1"], "test_fields": ["Haumea"], "n_train": 10,
    "variants": {v: {"n_pos": 5, "n_neg": 7, "fp_per_field": 1.0, "recall_snr_cut": 0.8,
                     "recall_model": r, "real_tnos_kept": True, "gate_passed": False}
                 for v, r in (("all_features", 0.7), ("without_snr", 0.6))},
}


@pytest.mark.parametrize("k, n, lo, hi", [(0, 58, 0.00, 0.06), (42, 50, 0.71, 0.92),
                                          (307, 567, 0.50, 0.58), (41, 41, 0.91, 1.00)])
def test_wilson_matches_documented_cells(k: int, n: int, lo: float, hi: float) -> None:
    a, b = wilson(k, n)
    assert round(a, 2) == lo and round(b, 2) == hi


def test_wilson_empty() -> None:
    assert wilson(0, 0) == (0.0, 1.0)


def test_coarse_bins_count_recovered_per_bin() -> None:
    flux = np.array([25.0, 60.0, 70.0, 150.0, 399.0])
    rec = np.array([False, True, False, True, True])
    rows = coarse_bins(flux, rec)
    assert [(r["k"], r["n"]) for r in rows] == [(0, 1), (1, 2), (1, 1), (1, 1)]


def _write_field(d: Path, name: str, known: bool) -> None:
    rng = np.random.default_rng(1)
    flux = np.exp(rng.uniform(np.log(0.02), np.log(0.4), 200))
    rec = flux > 0.07
    s = np.r_[[53.5] if known else [], 5.5, 7.5, 6.0, 8.0]
    y = np.r_[[2] if known else [], 0, 0, 0, 0].astype(int)
    r = np.array((["real"] if known else []) + ["real", "real", "null", "null"])
    np.savez_compressed(d / f"{name}.npz", S=s, Y=y, R=r, inj_flux=flux, inj_rec=rec,
                        extras=np.zeros(8, int))
    meta = {"name": name, "ra": 218.64, "dec": 15.04, "pass_index": 0, "n_frames": 58,
            "n_pass_frames": 60, "n_trials": 7132, "masked": 0.12,
            "pass_mjd": [60846.6, 60855.7], "real_ge7": [53.48, 7.5] if known else [7.5],
            "real_ge7_xy": [[127, 137], [10, 10]] if known else [[10, 10]],
            "n_real_ge5": 3 if known else 2, "n_null_ge5": 2}
    (d / f"{name}.json").write_text(json.dumps(meta))


def test_render_is_deterministic_and_excludes_the_tno(tmp_path: Path) -> None:
    _write_field(tmp_path, "Haumea", known=True)
    _write_field(tmp_path, "B1", known=False)
    rep = tmp_path / "vet_report.json"
    rep.write_text(json.dumps(REPORT))
    text = render(tmp_path, rep)
    assert text == render(tmp_path, rep)
    out = json.loads(text)
    assert [f["key"] for f in out["fields"]] == ["Haumea", "B1"]
    h = out["fields"][0]
    assert h["peaks"] == {"real_ge5": 2, "null_ge5": 2, "real_ge7": 1, "null_ge7": 1,
                          "real_max": 7.5, "null_max": 8.0}
    assert out["known_bodies"] == [{"name": "Haumea", "field": "Haumea", "v": 17.3,
                                    "delta_au": 49, "snr": 53.5, "rank": 1, "offset_px": 0.0,
                                    "offset_arcsec": 0.0}]
    assert out["pooled"]["n_injected"] == 400
    assert sum(b["n"] for b in out["pooled"]["bins"]) == 400
    assert out["classifier"]["passed"] is False
    assert out["classifier"]["recall_snr_cut"] == 0.8
    assert out["caveats"]


def test_mismatched_sample_counts_are_an_error(tmp_path: Path) -> None:
    _write_field(tmp_path, "B1", known=False)
    meta = json.loads((tmp_path / "B1.json").read_text()) | {"n_real_ge5": 9}
    (tmp_path / "B1.json").write_text(json.dumps(meta))
    rep = tmp_path / "vet_report.json"
    rep.write_text(json.dumps(REPORT))
    with pytest.raises(ValueError, match="disagree"):
        render(tmp_path, rep)
