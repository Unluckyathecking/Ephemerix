"""Gallery builds reuse an earlier view's Gaia and CatWISE lists when the live query fails."""

import json
import logging

import pytest
from build_fakes import GRID, MOVER, FakeSpherex, FakeWise

from pxs import blend, build, catalog_reuse, catalogs
from pxs.grid import Grid

GAIA_FAIL = "Gaia DR3 sources could not be fetched, so none are marked."
CW_FAIL = "CatWISE2020 sources could not be fetched, so none are marked."
G_ROW = {"id": "123", "ra": 133.775, "dec": -7.25, "epoch": 2016.0, "pmra_masyr": 1.0,
         "pmdec_masyr": -2.0, "g_mag": 15.0, "parallax_mas": 1.5, "parallax_error_mas": 0.1}
C_ROW = {"id": "J085506", "ra": 133.79, "dec": -7.24, "epoch": 2015.405, "pmra_masyr": 3.0,
         "pmdec_masyr": 4.0, "w1_mag": 14.0, "w2_mag": 13.5}
OUTSIDE = {**G_ROW, "id": "far", "ra": 133.78, "dec": -7.244 + 0.05}  # 3 arcmin north


def _stored(tmp_path, *, slug=MOVER.slug, grid=GRID, gaia=(G_ROW,), catwise=(C_ROW,),
            warnings=(), generated="2026-11-15T01:41:07Z"):
    m = {"generated": generated, "target": {"slug": slug},
         "center": {"ra": grid.center_ra, "dec": grid.center_dec},
         "fov_arcsec": grid.fov_arcsec, "size_px": grid.size_px,
         "overlays": {"gaia": list(gaia), "catwise": list(catwise)}, "warnings": list(warnings)}
    (tmp_path / MOVER.slug).mkdir(parents=True, exist_ok=True)
    (tmp_path / MOVER.slug / "manifest.json").write_text(json.dumps(m))
    return tmp_path


def _live(gaia=None, catwise=None):
    """Live overlays: a list is an answer, None a failed query."""
    warn = ([GAIA_FAIL] if gaia is None else []) + ([CW_FAIL] if catwise is None else [])
    return lambda grid: ({"gaia": gaia or [], "catwise": catwise or []}, warn)


def _run(stored_dir, live, grid=GRID):
    return catalog_reuse.with_stored(live, stored_dir, MOVER.slug)(grid)


def test_both_failed_reuses_both_lists_with_one_plain_note(tmp_path) -> None:
    ov, warn = _run(_stored(tmp_path), _live())
    assert ov == {"gaia": [G_ROW], "catwise": [C_ROW]}
    assert warn == [("The Gaia DR3 and CatWISE2020 lists were reused from the view built on "
                     "15 Nov 2026, because the catalogue services did not answer.")]
    assert not catalogs.gaia_failed(warn) and not catalogs.catwise_failed(warn)


def test_live_answer_is_kept_and_nothing_is_read(tmp_path) -> None:
    live = {"gaia": [OUTSIDE], "catwise": []}
    assert _run(tmp_path / "absent", lambda grid: (live, [])) == (live, [])


def test_only_the_failed_catalogue_is_replaced(tmp_path) -> None:
    ov, warn = _run(_stored(tmp_path), _live(gaia=[OUTSIDE]))
    assert ov == {"gaia": [OUTSIDE], "catwise": [C_ROW]}
    assert warn == [("The CatWISE2020 list was reused from the view built on 15 Nov 2026, "
                     "because the catalogue services did not answer.")]


def test_stored_field_smaller_than_the_new_one_is_refused(tmp_path, caplog) -> None:
    small = Grid(GRID.center_ra, GRID.center_dec, 120.0, 120)
    with caplog.at_level(logging.WARNING):
        out = _run(_stored(tmp_path, grid=small), _live())
    assert out == ({"gaia": [], "catwise": []}, [GAIA_FAIL, CW_FAIL])
    assert "does not cover" in caplog.text


def test_shifted_stored_field_is_refused(tmp_path) -> None:
    shifted = Grid(GRID.center_ra, GRID.center_dec + 10 / 3600, 240.0, 240)
    assert _run(_stored(tmp_path, grid=shifted), _live())[1] == [GAIA_FAIL, CW_FAIL]


def test_another_targets_manifest_is_refused(tmp_path) -> None:
    assert _run(_stored(tmp_path, slug="someone-else"), _live())[1] == [GAIA_FAIL, CW_FAIL]


def test_missing_manifest_leaves_the_failure(tmp_path) -> None:
    assert _run(tmp_path, _live())[1] == [GAIA_FAIL, CW_FAIL]


def test_list_the_earlier_build_also_failed_to_fetch_is_not_reused(tmp_path) -> None:
    ov, warn = _run(_stored(tmp_path, catwise=(), warnings=(CW_FAIL,)), _live())
    assert ov == {"gaia": [G_ROW], "catwise": []}
    assert CW_FAIL in warn and not catalogs.gaia_failed(warn)


def test_a_real_empty_list_is_reused_as_an_answer(tmp_path) -> None:
    """r-draconis: CatWISE answered with no sources; that is reused, not treated as failed."""
    ov, warn = _run(_stored(tmp_path, catwise=()), _live())
    assert ov["catwise"] == [] and not catalogs.catwise_failed(warn)


def test_larger_stored_field_is_cut_to_the_new_one(tmp_path) -> None:
    wide = Grid(GRID.center_ra, GRID.center_dec, 480.0, 480)
    ov, _ = _run(_stored(tmp_path, grid=wide, gaia=(G_ROW, OUTSIDE)), _live())
    assert ov["gaia"] == [G_ROW]


def test_date_of_an_earlier_reuse_is_carried_forward(tmp_path) -> None:
    earlier = catalog_reuse.reuse_note(["Gaia DR3", "CatWISE2020"], "14 Nov 2026")
    _, warn = _run(_stored(tmp_path, warnings=(earlier,)), _live())
    assert warn == [earlier]


@pytest.mark.parametrize("flag", [True, False])
def test_stored_overlays_give_the_same_view_as_live_ones(tmp_path, flag) -> None:
    """Through build_view: the reused lists drive the same decisions, and the view is not
    marked partial because nothing is missing."""
    stored = _stored(tmp_path / "pub", grid=build.choose_grid(MOVER, build.GridParams())[0])
    up = build.build_view(MOVER, build.GridParams(), FakeSpherex(MOVER), FakeWise(MOVER),
                          tmp_path / "up", overlays=_live([G_ROW], [C_ROW]))
    down_ov = catalog_reuse.with_stored(_live(), stored, MOVER.slug) if flag else _live()
    down = build.build_view(MOVER, build.GridParams(), FakeSpherex(MOVER), FakeWise(MOVER),
                            tmp_path / "down", overlays=down_ov)
    if not flag:
        assert down["degraded"] and blend.CHECKS_NOT_RUN in down["warnings"]
        return
    note = [w for w in down["warnings"] if "reused" in w]
    assert len(note) == 1 and not down["degraded"]
    same = ("overlays", "frames", "measured_motion", "match", "degraded")
    assert {k: down.get(k) for k in same} == {k: up.get(k) for k in same}
    assert [w for w in down["warnings"] if w not in note] == up["warnings"]


@pytest.mark.parametrize("extra", [[], ["--catalogs-from", "pub"]])
def test_cli_option_is_off_by_default(tmp_path, monkeypatch, extra) -> None:
    seen = []

    def fake_build(t, params, spx, wise, out, overlays=None):
        seen.append(overlays)
        raise build.BuildError("stop")
    monkeypatch.setattr(build, "build_view", fake_build)
    monkeypatch.setattr(build, "real_source", lambda name: None)
    slug = build.load_targets(build.REPO / "data" / "targets.json")[0].slug
    build.main(["--target", slug, "--out", str(tmp_path), *extra])
    assert (seen[0] is None) == (not extra)
