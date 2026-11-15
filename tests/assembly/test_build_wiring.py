"""Library features wired into the build: Gaia neighbours for SPHEREx recentring, a known
parallax in the motion fit, per-pass agreement in `match` and gallery groups (the pair model
curve is tested in tests/test_typing_pairs.py)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from build_fakes import MOVER, FakeSpherex, FakeWise, no_overlays

from pxs import blend, build, catalogs
from pxs.astrometry import decimal_year, propagate
from pxs.sources import load_targets

PARAMS = build.GridParams(240.0, 240)
REPO = Path(__file__).resolve().parents[2]


class RecordingSpherex(FakeSpherex):
    """FakeSpherex that records the neighbours each pass's spectrum was given."""

    def __init__(self, target):
        super().__init__(target)
        self.seen: dict[float, object] = {}

    def extract_spectrum(self, pas, target, neighbours=None):
        self.seen[pas.mjd_start] = neighbours
        return super().extract_spectrum(pas, target)


def _self_row() -> dict:
    """MOVER's own Gaia row (2016.0 epoch, same motion)."""
    ra, dec = propagate(MOVER.ra, MOVER.dec, MOVER.epoch, MOVER.pmra_masyr, MOVER.pmdec_masyr,
                        2016.0)
    return {"id": "self", "ra": float(ra), "dec": float(dec), "epoch": 2016.0,
            "pmra_masyr": MOVER.pmra_masyr, "pmdec_masyr": MOVER.pmdec_masyr, "g_mag": 19.0,
            "parallax_mas": 439.0, "parallax_error_mas": 2.0}


STAR = {"id": "star", "ra": 133.77, "dec": -7.25, "epoch": 2016.0, "pmra_masyr": 0.0,
        "pmdec_masyr": 1000.0, "g_mag": 12.0, "parallax_mas": 1.0, "parallax_error_mas": 0.1}


def _with(gaia, warnings=()):
    return lambda grid: ({"gaia": gaia, "catwise": []}, list(warnings))


def _build(tmp_path, spx, overlays, target=MOVER):
    return build.build_view(target, PARAMS, spx, FakeWise(target), tmp_path, overlays=overlays)


# --- 1. Gaia neighbours reach the SPHEREx spectrum -----------------------------------------

def test_spectrum_gets_gaia_neighbours_at_the_pass_epoch_without_the_target(tmp_path) -> None:
    spx = RecordingSpherex(MOVER)
    _build(tmp_path, spx, _with([_self_row(), STAR]))
    assert len(spx.seen) == 2
    for mjd0, nb in spx.seen.items():
        pas = next(p for p in spx.group_passes(spx.find_frames(0, 0)) if p.mjd_start == mjd0)
        year = float(decimal_year(0.5 * (pas.mjd_start + pas.mjd_end)))
        ra, dec = propagate(STAR["ra"], STAR["dec"], 2016.0, 0.0, 1000.0, year)
        assert nb == [pytest.approx((float(ra), float(dec)), abs=1e-9)]


def test_failed_gaia_query_gives_none_not_an_empty_list(tmp_path) -> None:
    spx = RecordingSpherex(MOVER)
    _build(tmp_path, spx, _with([], ["Gaia DR3 sources could not be fetched, so none are marked."]))
    assert set(spx.seen.values()) == {None}


def test_failed_catwise_query_still_gives_the_gaia_neighbours(tmp_path) -> None:
    spx = RecordingSpherex(MOVER)
    _build(tmp_path, spx, _with([], ["CatWISE2020 sources could not be fetched, so none are marked."]))
    assert all(nb == [] for nb in spx.seen.values())


def test_gaia_failure_is_recognised_from_the_catalogue_warnings() -> None:
    assert catalogs.gaia_failed(["Gaia DR3 sources could not be fetched, so none are marked."])
    assert not catalogs.gaia_failed(["CatWISE2020 sources could not be fetched, so none are marked."])


def test_gaia_query_and_rows_carry_parallax(monkeypatch) -> None:
    from build_fakes import GRID
    assert "parallax, parallax_error" in catalogs.gaia_query(GRID)
    text = ("source_id,ra,dec,pmra,pmdec,phot_g_mean_mag,parallax,parallax_error\n"
            f"1,{GRID.center_ra},{GRID.center_dec},1,2,12,5.5,0.2\n")
    row = catalogs.parse_gaia(text, GRID)[0]
    assert row["parallax_mas"] == 5.5 and row["parallax_error_mas"] == 0.2


# --- 2. Parallax in the motion fit ---------------------------------------------------------

def test_targets_file_parallax_is_fixed_in_the_motion_fit(tmp_path) -> None:
    t = replace(MOVER, parallax_mas=439.0)
    m = _build(tmp_path, FakeSpherex(t), no_overlays, t)
    assert m["measured_motion"]["parallax_model"] == "fixed"
    assert m["measured_motion"]["parallax_mas"] == 439.0


def test_gaia_parallax_of_the_target_is_used_when_the_file_has_none(tmp_path) -> None:
    m = _build(tmp_path, FakeSpherex(MOVER), _with([_self_row(), STAR]))
    assert m["measured_motion"]["parallax_mas"] == 439.0


@pytest.mark.parametrize("plx,err", [(439.0, 200.0), (-3.0, 0.5), (None, None)])
def test_weak_or_missing_gaia_parallax_is_not_fixed(plx, err) -> None:
    row = {**_self_row(), "parallax_mas": plx, "parallax_error_mas": err}
    assert blend.target_parallax(MOVER, [row, STAR]) is None


def test_file_parallax_wins_over_gaia() -> None:
    t = replace(MOVER, parallax_mas=400.0)
    assert blend.target_parallax(t, [_self_row()]) == 400.0


# --- 3. Per-pass agreement -----------------------------------------------------------------

def test_match_carries_per_pass_calls_and_their_agreement(tmp_path) -> None:
    m = _build(tmp_path, FakeSpherex(MOVER), no_overlays)
    per = m["match"]["per_pass"]
    assert [p["id"] for p in per] == ["spx-2025a", "spx-2025b"]
    labels = {s["id"]: s["label"] for s in m["spectra"]}
    for p in per:
        assert p["label"] == labels[p["id"]]
        assert p["typed"] and p["class"] == m["match"]["class"]
        assert p["type"]
    agree = m["match"]["pass_agreement"]
    assert agree["status"] == "agree" and agree["sentence"]


def test_withheld_match_has_no_per_pass_block(tmp_path) -> None:
    # A static Gaia star as bright as the target, on its 2025 path, blocks the typing.
    ra, dec = propagate(MOVER.ra, MOVER.dec, MOVER.epoch, MOVER.pmra_masyr, MOVER.pmdec_masyr,
                        2025.3)
    twin = {"id": "twin", "ra": float(ra), "dec": float(dec), "epoch": 2025.3,
            "pmra_masyr": 0.0, "pmdec_masyr": 0.0, "g_mag": 19.2}
    m = _build(tmp_path, FakeSpherex(MOVER), _with([_self_row(), twin]))
    assert m["match"] is None


# --- 4. Gallery groups ---------------------------------------------------------------------

def test_index_entry_carries_the_group(tmp_path) -> None:
    t = replace(MOVER, group="Brown dwarfs")
    assert build.index_entry(t, {"match": None})["group"] == "Brown dwarfs"
    assert build.index_entry(MOVER, {"match": None})["group"] is None


def test_targets_file_groups_and_parallaxes_load() -> None:
    targets = {t.slug: t for t in load_targets(REPO / "data" / "targets.json")}
    raw = {e["slug"]: e for e in json.loads((REPO / "data" / "targets.json").read_text())}
    assert all(t.group for t in targets.values())
    for slug, t in targets.items():
        assert t.group == raw[slug]["group"]
        assert t.parallax_mas == raw[slug].get("parallax_mas")
    assert targets["barnards-star"].parallax_mas == pytest.approx(546.976)


# --- The gate is told whether the neighbour checks could be made ---------------------------

@pytest.mark.parametrize(("w2", "warnings", "expected"), [
    (14.4, [], True),
    (None, [], False),  # no catalogued brightness: a neighbour's share cannot be estimated
    (14.4, ["Gaia DR3 sources could not be fetched, so none are marked."], False),
    (14.4, ["CatWISE2020 sources could not be fetched, so none are marked."], False),
])
def test_the_gate_learns_whether_the_neighbour_checks_ran(tmp_path, monkeypatch, w2, warnings,
                                                          expected) -> None:
    seen = {}
    real = build.typegate.vet

    def vet(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(build.typegate, "vet", vet)
    _build(tmp_path, FakeSpherex(MOVER), _with([], warnings), target=replace(MOVER, w2_mag=w2))
    assert seen["checked"] is expected


# --- The field mover search is part of every view ------------------------------------------

def test_the_view_says_what_else_moved_or_why_it_was_not_searched(tmp_path) -> None:
    m = _build(tmp_path / "a", FakeSpherex(MOVER), _with([]))
    fm = m["field_movers"]
    assert fm["status"] == "searched" and fm["n_epochs"] == {"W2": 8, "W1": 8}
    assert [x["label"] for x in fm["movers"]] == ["target"]  # found without its position
    assert set(fm["movers"][0]["epochs"]) <= {f["id"] for f in m["frames"]}
    assert json.loads((tmp_path / "a" / "manifest.json").read_text())["field_movers"] == fm
    down = _build(tmp_path / "b", FakeSpherex(MOVER),
                  _with([], ["Gaia DR3 sources could not be fetched, so none are marked."]))
    assert down["field_movers"]["status"] == "not_searched"
    assert "could not be fetched" in down["field_movers"]["sentence"]
