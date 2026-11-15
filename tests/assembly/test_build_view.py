import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from build_fakes import MOVER, FakeSpherex, FakeWise, no_overlays

from pxs import blend, build, catalogs
from pxs.manifest import ManifestError, validate

PARAMS = build.GridParams(240.0, 240)


@pytest.fixture(scope="module")
def view(tmp_path_factory) -> tuple[dict, Path]:
    out = tmp_path_factory.mktemp("view")
    # The source really moves 3% faster than the catalogue says, so the measured motion
    # must come from the images, not from the prediction.
    m = build.build_view(MOVER, PARAMS, FakeSpherex(MOVER), FakeWise(MOVER, pm_scale=1.03), out,
                         overlays=no_overlays)
    return m, out


def test_full_view_is_valid_and_complete(view) -> None:
    m, out = view
    validate(json.loads((out / "manifest.json").read_text()), out)
    assert (out / "thumb.png").is_file()
    bands = {f["band"] for f in m["frames"]}
    assert bands == {"W1", "W2", "spx-b1", "spx-b2", "spx-b3", "spx-b4", "spx-b5", "spx-b6"}
    assert [f["mjd"] for f in m["frames"]] == sorted(f["mjd"] for f in m["frames"])
    assert len(m["track"]) == 18
    assert [s["id"] for s in m["spectra"]] == ["spx-2025a", "spx-2025b", "spx-all"]
    assert m["match"]["spectrum_id"] in {"spx-2025a", "spx-2025b", "spx-all"}
    assert m["features"]
    assert m["frames"][0]["id"] == "wise-w1-2010a"


def test_target_is_detected_near_truth_in_every_wise_frame(view) -> None:
    m, _ = view
    wise = [f for f in m["frames"] if f["mission"] == "WISE"]
    assert all(f["centroid_px"] is not None for f in wise)


def test_measured_motion_recovers_injected_motion(view) -> None:
    m, _ = view
    mm = m["measured_motion"]
    true_ra, true_dec = MOVER.pmra_masyr * 1.03, MOVER.pmdec_masyr * 1.03
    assert abs(mm["pmra_masyr"] - true_ra) < 3 * mm["err_masyr"]
    assert abs(mm["pmdec_masyr"] - true_dec) < 3 * mm["err_masyr"]
    # ...and is distinguishable from the catalogue value it was predicted with.
    assert abs(mm["pmra_masyr"] - MOVER.pmra_masyr) > 3 * mm["err_masyr"]
    # one band per mission: 8 WISE visits (W2 only) + 2 SPHEREx passes
    assert mm["n_detections"] == 10


def test_broken_manifest_fails_with_clear_message(view) -> None:
    m, out = view
    bad = copy.deepcopy(m)
    bad["frames"][0]["band"] = "W3"
    bad["frames"][1]["centroid_px"] = [float("nan"), 3.0]
    bad["frames"][2]["image"] = "frames/missing.png"
    del bad["center"]
    with pytest.raises(ManifestError) as err:
        validate(bad, out)
    msg = str(err.value)
    for needle in ("band must be one of", "not strict JSON", "missing.png does not exist",
                   "center must have"):
        assert needle in msg


def test_failing_wise_still_builds_with_a_warning(tmp_path: Path) -> None:
    m = build.build_view(MOVER, PARAMS, FakeSpherex(MOVER), FakeWise(MOVER, fail=True), tmp_path,
                         overlays=no_overlays)
    validate(m, tmp_path)
    assert {f["mission"] for f in m["frames"]} == {"SPHEREx"}
    assert any("WISE images could not be loaded" in w for w in m["warnings"])


def test_no_sources_at_all_is_a_build_error(tmp_path: Path) -> None:
    with pytest.raises(build.BuildError):
        build.build_view(MOVER, PARAMS, None, None, tmp_path, overlays=no_overlays)


def test_grid_widens_for_a_long_path() -> None:
    fast = replace(MOVER, pmra_masyr=-12000.0, pmdec_masyr=6000.0)
    grid, warn = build.choose_grid(fast, PARAMS)
    assert grid.fov_arcsec > 240 and grid.pixscale_arcsec == pytest.approx(1.0)
    assert "widened" in warn[0]
    from pxs.astrometry import track
    pts = track({"ra": fast.ra, "dec": fast.dec, "epoch": fast.epoch,
                 "pmra_masyr": fast.pmra_masyr, "pmdec_masyr": fast.pmdec_masyr},
                {"ra": grid.center_ra, "dec": grid.center_dec}, grid.fov_arcsec, grid.size_px)
    margin = 0.05 * grid.size_px
    assert all(margin < c < grid.size_px - margin for p in pts for c in p["px"])


def test_cli_all_writes_index_of_built_targets(tmp_path: Path, monkeypatch) -> None:
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps([
        {"name": "Fast mover", "slug": "fast-mover", "ra": MOVER.ra, "dec": MOVER.dec,
         "epoch": MOVER.epoch, "pmra_masyr": MOVER.pmra_masyr, "pmdec_masyr": MOVER.pmdec_masyr,
         "blurb": "A test.", "known_type": "Y4"},
        {"name": "No motion", "ra": 10.0, "dec": 20.0, "epoch": 2016.0},
    ]))
    out = tmp_path / "gallery"
    (out / "old").mkdir(parents=True)
    (out / "index.json").write_text(json.dumps({"schema": 1, "targets": [{"slug": "old"}]}))
    monkeypatch.setattr(build.catalogs, "overlays", no_overlays)
    fakes = {"pxs.wise": FakeWise(MOVER), "pxs.spherex": FakeSpherex(MOVER)}
    monkeypatch.setattr(build, "real_source", fakes.get)
    assert build.main(["--all", "--out", str(out), "--targets", str(targets)]) == 0
    index = json.loads((out / "index.json").read_text())
    slugs = [t["slug"] for t in index["targets"]]
    assert slugs == ["fast-mover", "no-motion"]
    first = index["targets"][0]
    assert first["known_type"] == "Y4" and first["tool_type"].startswith("T")
    assert first["ra"] == MOVER.ra and first["thumb"] == "fast-mover/thumb.png"
    for t in index["targets"]:
        validate(json.loads((out / t["manifest"]).read_text()), out / t["slug"])
    nomo = json.loads((out / "no-motion" / "manifest.json").read_text())
    assert nomo["track"] == [] and all(f["predicted_px"] is None for f in nomo["frames"])


def test_failure_marks_the_view_degraded(tmp_path: Path) -> None:
    m = build.build_view(MOVER, PARAMS, FakeSpherex(MOVER), FakeWise(MOVER, fail=True), tmp_path,
                         overlays=no_overlays)
    assert m["degraded"] is True


def test_clean_view_is_not_degraded(view) -> None:
    assert view[0]["degraded"] is False
    assert blend.CHECKS_NOT_RUN not in view[0]["warnings"]


def test_missing_catwise_says_the_neighbour_checks_were_not_run(tmp_path: Path) -> None:
    def no_catwise(grid):
        return {"gaia": [], "catwise": []}, [catalogs._failed(catalogs.CATWISE)]

    m = build.build_view(MOVER, PARAMS, FakeSpherex(MOVER), FakeWise(MOVER), tmp_path,
                         overlays=no_catwise)
    assert blend.CHECKS_NOT_RUN in m["warnings"] and m["degraded"] is True


class PathWise(FakeWise):
    """Records how visits are searched (code review B1)."""

    def __init__(self, target):
        super().__init__(target)
        self.calls = []

    def path_from_motion(self, ra, dec, epoch, pmra, pmdec):
        return [("path", ra, dec, epoch, pmra, pmdec)]

    def find_visits(self, ra, dec, path=None):
        self.calls.append(path)
        return super().find_visits(ra, dec)


class TargetSpherex(FakeSpherex):
    def __init__(self, target):
        super().__init__(target)
        self.seen = []

    def find_frames_for_target(self, target):
        self.seen.append(target)
        return self.find_frames(target.ra, target.dec)


def test_a_mover_is_searched_along_its_path(tmp_path: Path) -> None:
    wise, spx = PathWise(MOVER), TargetSpherex(MOVER)
    build.build_view(MOVER, PARAMS, spx, wise, tmp_path, overlays=no_overlays)
    assert wise.calls == [[("path", MOVER.ra, MOVER.dec, MOVER.epoch, MOVER.pmra_masyr,
                            MOVER.pmdec_masyr)]]
    assert spx.seen == [MOVER]


def test_a_failing_centroid_does_not_abort_the_view(tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise IndexError("boolean index did not match")

    monkeypatch.setattr(build.centroid, "detect", boom)
    m = build.build_view(MOVER, PARAMS, FakeSpherex(MOVER), FakeWise(MOVER), tmp_path,
                         overlays=no_overlays)
    assert all(f["centroid_px"] is None for f in m["frames"])
    assert "the position could not be measured in this frame" in m["frames"][0]["warnings"]


def test_cli_reports_failed_targets(tmp_path: Path, monkeypatch, caplog) -> None:
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps([{"name": "No motion", "ra": 10.0, "dec": 20.0,
                                    "epoch": 2016.0}]))
    monkeypatch.setattr(build, "real_source", lambda name: None)  # no data at all: fails
    assert build.main(["--all", "--out", str(tmp_path / "g"), "--targets", str(targets)]) == 1
    assert "1 of 1 targets failed and are not in the index: no-motion" in caplog.text
