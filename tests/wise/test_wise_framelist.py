"""Committed frame lists replace the IRSA search; NEOWISE scores come from the source table."""

import json
from pathlib import Path

import pyarrow as pa
import pytest
import requests

from pxs.wise import framelist, neoqual, net, search
from pxs.wise.frames import Frame

CORNERS = ((248.0, 66.5), (248.5, 66.5), (248.5, 67.0), (248.0, 67.0))
FRAME = Frame("neowiser", "82375a", 268, "W2", 58000.5, CORNERS, qual_frame=10, saa_sep_deg=12.5)
OLD = Frame("allsky", "04097b", 218, "W1", 55315.1, CORNERS)


def _write(root: Path, name: str = "rdra.json", frames=(FRAME, OLD), **phases: str) -> Path:
    status = {"allsky": "complete", "3band": "none", "postcryo": "none", "neowiser": "complete"}
    status.update(phases)
    doc = {"version": 1, "ra": 248.167, "dec": 66.755, "radius_deg": 0.01, "made": "2026-11-14",
           "phases": {k: {"status": v, "how": "test"} for k, v in status.items()},
           "frames": [framelist.to_row(f) for f in frames]}
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "lists"
    monkeypatch.setenv(framelist.ENV_DIR, str(root))
    return root


def test_row_round_trip_keeps_every_field() -> None:
    back = framelist.to_frame(json.loads(json.dumps(framelist.to_row(FRAME))))
    assert back == FRAME


def test_lookup_serves_a_containing_list_and_states_unscored_phases(lists: Path) -> None:
    _write(lists)
    frames, missing = framelist.lookup(248.1675, 66.755, 0.002)
    assert [f.key for f in frames] == [OLD.key, FRAME.key]  # sorted by time
    assert missing == []
    assert framelist.warnings(frames, missing) == (framelist.no_quality_warning(["allsky"]),)


def test_lookup_ignores_circles_outside_the_list(lists: Path) -> None:
    _write(lists)
    assert framelist.lookup(248.167, 66.755, 0.02) is None  # bigger than the list's circle
    assert framelist.lookup(10.0, 10.0, 0.002) is None


def test_missing_phase_is_partial_with_the_search_sentence(lists: Path) -> None:
    _write(lists, **{"3band": "missing"})
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert frames.partial
    assert "2010 (three-band) failed" in frames.warnings[-1]


def test_a_broken_list_falls_back_to_the_search(lists: Path) -> None:
    lists.mkdir()
    (lists / "bad.json").write_text("{not json")
    assert framelist.lookup(248.167, 66.755, 0.002) is None


def test_search_uses_the_list_without_touching_irsa(lists: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    _write(lists)

    def no_network(*args, **kwargs):
        raise AssertionError("IRSA was queried")

    monkeypatch.setattr(net, "get_text", no_network)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert len(frames) == 2 and not frames.partial


def test_scores_take_one_value_per_frame() -> None:
    t = pa.table({"scan_id": ["82375a", "82375a", "71370a"], "frame_num": [268, 268, 274],
                  "qual_frame": [10, 10, 0], "saa_sep": [12.5, 12.5, -3.8]})
    assert neoqual.scores([t]) == {("82375a", 268): (10, 12.5), ("71370a", 274): (0, -3.8)}
    assert neoqual.scores([]) == {}


def test_pixels_are_order5_nested() -> None:
    assert neoqual.pixels(110.6124, -5.6745, 0.0046) == [5432]  # checked against the bucket
    assert neoqual.partition_dir("year5", 5432).endswith("healpix_k0=5/healpix_k5=5432")


def test_tap_failure_takes_neowise_scores_from_the_source_table(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from test_wise_search_fallback import _sia

    def fake(url: str, params: dict, **kwargs) -> str:
        if url == search.SIA_URL:
            return _sia(params)
        raise requests.HTTPError("HTTP 502")

    monkeypatch.setattr(net, "get_text", fake)
    monkeypatch.setattr(neoqual, "quality", lambda *a: {("82375a", 268): (0, -3.8),
                                                        ("71370a", 274): (10, 40.0)})
    frames = search.search_frames(248.167, 66.755, 0.002)
    neo = [f for f in frames if f.phase == "neowiser"]
    assert neo and {f.qual_frame for f in neo} == {0, 10}
    assert all(f.qual_frame is None for f in frames if f.phase != "neowiser")


def test_a_cached_tap_answer_completes_a_listed_phase(lists: Path) -> None:
    from test_wise_search_fallback import FIXTURES

    _write(lists, **{"3band": "missing"})
    params = search._tap_params(search.PHASES[1], 248.167, 66.755, 0.002)  # 3band
    path = net._query_path(search.TAP_URL, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((FIXTURES / "tap_allsky_3band_p1bm_frm.csv").read_text())
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert not frames.partial
    assert any(f.phase == "3band" for f in frames)
