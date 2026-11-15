import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from build_fakes import GRID, MOVER, FakeSpecPoint, FakeSpherex

from pxs import catalogs, spectra
from pxs.sources import TargetError, load_targets


def _pt(wl, flux, err, flagged=False, mjd=60700.0):
    return FakeSpecPoint(wl, wl / 40, flux, err, 1, flagged, mjd)


def test_combined_bin_is_inverse_variance_mean_and_skips_flagged() -> None:
    a = [_pt(2.000, 1.0, 1.0), _pt(2.001, 99.0, 0.1, flagged=True)]
    b = [_pt(2.002, 3.0, 1.0, mjd=60900.0)]
    out = spectra.combined_spectrum([a, b])
    good = [p for p in out["points"] if not p["flagged"]]
    assert len(good) == 1
    assert good[0]["flux"] == pytest.approx(2.0)
    assert good[0]["err"] == pytest.approx(1.0 / np.sqrt(2.0))


def test_unequal_errors_weight_the_mean() -> None:
    out = spectra.combined_spectrum([[_pt(4.5, 1.0, 1.0)], [_pt(4.5, 4.0, 2.0, mjd=60900.0)]])
    p = out["points"][0]
    assert p["flux"] == pytest.approx((1.0 + 4.0 / 4) / (1 + 1 / 4))
    assert p["err"] == pytest.approx((1 + 1 / 4) ** -0.5)


def test_bins_match_resolution() -> None:
    edges = spectra.bin_edges(1.0, 5.0)
    widths = np.diff(edges)
    lo = edges[:-1]
    r = lo / widths
    assert np.allclose(r[lo < 3.8], 40.0) and np.allclose(r[lo >= 3.8], 120.0)


def test_bin_with_only_flagged_points_is_a_flagged_point() -> None:
    out = spectra.combined_spectrum([[_pt(1.5, None, None, flagged=True)],
                                     [_pt(1.5, None, None, flagged=True, mjd=60900.0)]])
    assert out["points"] == [{**out["points"][0], "flux": None, "flagged": True}]


def test_build_spectra_carries_flags_and_attaches_match() -> None:
    fake = FakeSpherex(MOVER)
    passes = [fake.extract_spectrum(p, MOVER) for p in fake.group_passes(fake.find_frames(0, 0))]
    specs, match = spectra.build_spectra(passes)
    assert [s["id"] for s in specs] == ["spx-2025a", "spx-2025b", "spx-all"]
    assert sum(p["flagged"] for p in specs[0]["points"]) == 1
    assert match is not None
    assert match["spectrum_id"] in {s["id"] for s in specs}
    assert match["best"]["type"].startswith("T")
    json.dumps(specs, allow_nan=False)


def _fake_match(seen, typeable=()):
    """A stand-in for spectra._match that records calls and returns a brown-dwarf T5."""
    def f(spec, pairs=True):
        seen.append(spec["id"])
        return {"spectrum_id": spec["id"], "class": "brown dwarf", "best": {"type": "T5"},
                "type_range": ["T4", "T6"]}
    return f


def _bright(mjd, n=40):
    return [FakeSpecPoint(1.0 + 0.1 * i, 0.025, 10.0, 0.1, 1 + i % 6, False, mjd)
            for i in range(n)]


def test_two_passes_type_the_combined_spectrum(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(spectra, "_match", _fake_match(seen))
    _, match = spectra.build_spectra([_bright(60700.0), _bright(60900.0)])
    assert seen == ["spx-all"] and match["spectrum_id"] == "spx-all"


def test_a_combined_spectrum_that_fails_the_gate_falls_back_to_a_pass(monkeypatch) -> None:
    monkeypatch.setattr(spectra, "_match", _fake_match([]))
    gated = {"spx-all"}
    monkeypatch.setattr(spectra, "faint_reason",
                        lambda spec: "too faint" if spec["id"] in gated else None)
    _, match = spectra.build_spectra([_bright(60700.0), _bright(60900.0, n=50)])
    assert match["spectrum_id"] == "spx-2025b"  # the pass with more clear detections
    gated |= {"spx-2025a", "spx-2025b"}
    _, match = spectra.build_spectra([_bright(60700.0), _bright(60900.0)])
    assert match["spectrum_id"] == "spx-all"  # nothing passes: the gate will withhold it


def test_per_pass_agreement(monkeypatch) -> None:
    types = {"spx-2025a": "T5", "spx-2025b": "T6", "spx-2026a": "T9", "spx-all": "T5"}

    def match(spec, pairs=True):
        return {"spectrum_id": spec["id"], "class": "brown dwarf",
                "best": {"type": types[spec["id"]]}, "type_range": ["T4", "T6"]}

    monkeypatch.setattr(spectra, "_match", match)
    passes = [_bright(60700.0), _bright(60900.0), _bright(61100.0)]
    out = spectra.build_all(passes)
    assert out.agreement.status == "disagree"
    assert "spx-2026a: brown dwarf, T9" in out.agreement.sentence
    types["spx-2026a"] = "T4"
    out = spectra.build_all(passes)
    assert out.agreement.status == "agree"
    assert out.agreement.sentence == "All 3 passes typed on their own agree."
    assert [p["best"] for p in out.agreement.as_dict()["passes"]] == ["T5", "T6", "T4"]


def test_passes_too_faint_alone_are_not_typed_not_disagreeing(monkeypatch) -> None:
    monkeypatch.setattr(spectra, "_match", _fake_match([]))
    monkeypatch.setattr(spectra, "faint_reason",
                        lambda spec: None if spec["id"] in ("spx-all", "spx-2025a") else "faint")
    out = spectra.build_all([_bright(60700.0), _bright(60900.0)])
    assert out.agreement.status == "too few"
    assert [p.typed for p in out.agreement.passes] == [True, False]


def test_load_targets_reports_bad_entries(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([{"name": "Ok", "ra": 1.0, "dec": 2.0, "epoch": 2016.0},
                                {"name": "Eps Ind B", "ra_deg": 331.0, "dec_deg": -56.8,
                                 "epoch": 2016.0}]))
    with pytest.raises(TargetError, match=r"entry 1 \('Eps Ind B'\).*missing \['ra', 'dec'\].*ra_deg"):
        load_targets(path)


def test_load_targets_derives_slug_and_ignores_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([{"name": "WISE 0855-0714", "ra": 133.78, "dec": -7.24,
                                 "epoch": 2015.4, "pmra_masyr": -8123.7, "pmdec_masyr": 673.2,
                                 "parallax_mas": 439.0}]))
    (t,) = load_targets(path)
    assert t.slug == "wise-0855-0714" and t.has_pm


def test_load_targets_rejects_half_proper_motion(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps([{"name": "X", "ra": 1.0, "dec": 2.0, "epoch": 2016.0,
                                 "pmra_masyr": 5.0}]))
    with pytest.raises(TargetError, match="both proper-motion components"):
        load_targets(path)


GAIA_CSV = """source_id,ra,dec,pmra,pmdec,phot_g_mean_mag
1,133.78,-7.244,10.5,-3.0,12.1
2,133.95,-7.244,,,13.0
"""
CATWISE_CSV = """source_name,ra_pm,dec_pm,pmra,pmdec,w1mpro,w2mpro
J0855,133.7835,-7.2440,-8.1,0.67,17.3,14.0
"""


def test_catalogs_parse_filter_and_scale(tmp_path: Path) -> None:
    calls = []

    def fetch(url: str, adql: str) -> str:
        calls.append(url)
        return GAIA_CSV if url == catalogs.GAIA_TAP else CATWISE_CSV

    ov, warn = catalogs.overlays(GRID, fetch=fetch, cache_dir=tmp_path)
    assert warn == []
    assert [s["id"] for s in ov["gaia"]] == ["1"]  # source 2 lies outside the field
    assert ov["catwise"][0]["pmra_masyr"] == pytest.approx(-8100.0)
    assert ov["catwise"][0]["epoch"] == pytest.approx(2015.4025, abs=1e-3)  # MJD 57170
    catalogs.overlays(GRID, fetch=fetch, cache_dir=tmp_path)
    assert len(calls) == 2  # second call served from the disk cache


def test_catalog_failure_gives_empty_list_and_warning(tmp_path: Path) -> None:
    def fetch(url: str, adql: str) -> str:
        raise ConnectionError("down")

    ov, warn = catalogs.overlays(GRID, fetch=fetch, cache_dir=tmp_path)
    assert ov == {"gaia": [], "catwise": []}
    assert len(warn) == 2 and "Gaia DR3" in warn[0]
    assert not list(tmp_path.iterdir())  # failures are not cached


def test_passes_with_no_usable_point_give_no_spectrum() -> None:
    # Barnard's Star: every frame saturated in every pass.
    sat = [_pt(2.0 + 0.1 * i, None, None, flagged=True) for i in range(10)]
    assert spectra.build_spectra([sat, sat]) == ([], None)
    good = [_pt(2.0 + 0.1 * i, 1.0, 0.1, mjd=60900.0) for i in range(10)]
    out, _ = spectra.build_spectra([sat, good])
    assert [s["id"] for s in out] == ["spx-2025a"]


def test_catalogs_fall_back_to_data_lab_when_the_primary_fails(tmp_path: Path) -> None:
    calls = []

    def fetch(url: str, adql: str) -> str:
        calls.append((url, adql))
        if url != catalogs.DATALAB_TAP:
            raise ConnectionError("IRSA down")
        return GAIA_CSV if "gaia_dr3.gaia_source" in adql else CATWISE_CSV

    ov, warn = catalogs.overlays(GRID, fetch=fetch, cache_dir=tmp_path)
    assert warn == []
    assert [s["id"] for s in ov["gaia"]] == ["1"] and ov["catwise"][0]["id"] == "J0855"
    lab = [q for u, q in calls if u == catalogs.DATALAB_TAP]
    assert len(lab) == 2 and all("Q3C_RADIAL_QUERY" in q and "CONTAINS" not in q for q in lab)
    assert any("FROM catwise2020.main" in q for q in lab)


def test_a_slow_primary_gives_way_after_the_head_start(tmp_path: Path) -> None:
    release = threading.Event()

    def fetch(url: str, adql: str) -> str:
        if url == catalogs.DATALAB_TAP:
            return GAIA_CSV if "gaia_dr3" in adql else CATWISE_CSV
        release.wait(5)
        return ""

    start = time.monotonic()
    text = catalogs.first_answer([lambda: fetch(catalogs.IRSA_TAP, "q"),
                                  lambda: fetch(catalogs.DATALAB_TAP, "catwise")], after_s=0.1)
    release.set()
    assert text == CATWISE_CSV and time.monotonic() - start < 2
