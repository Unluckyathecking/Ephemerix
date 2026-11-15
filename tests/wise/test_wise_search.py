import pytest
from conftest import FIXTURES

from pxs.wise import net, search
from pxs.wise.frames import merge, parse_sia, parse_tap


def _sia(name: str) -> str:
    return (FIXTURES / f"sia_{name}.csv").read_text()


def _tap(table: str) -> str:
    return (FIXTURES / f"tap_{table}.csv").read_text()


def test_parse_sia_keeps_only_int_w1_w2_frames() -> None:
    frames = parse_sia(_sia("neowiser"))
    assert len(frames) == 4  # 2 exposures x W1, W2 (unc, msk and artefact rows dropped)
    assert {f.band for f in frames} == {"W1", "W2"}
    assert all(len(f.corners) == 4 and f.qual_frame is None for f in frames)
    assert parse_sia(_sia("wise_3bandcryo")) == []  # SIA's 3-band collection is empty


def test_parse_tap_reads_quality_and_corners() -> None:
    frames = parse_tap(_tap("allsky_2band_p1bm_frm"), "postcryo")
    f = next(f for f in frames if f.scan_id == "10885b" and f.band == "W1")
    assert (f.frame_num, f.qual_frame) == (21, 5)
    assert f.moon_sep_deg == pytest.approx(94.192)
    assert f.corners[0] == pytest.approx((248.210391541201, 66.596521548419))


def test_merge_attaches_quality_and_keeps_tap_only_frames() -> None:
    sia = parse_sia(_sia("wise_2bandcryo"))
    tap = parse_tap(_tap("allsky_2band_p1bm_frm"), "postcryo")
    tap3 = parse_tap(_tap("allsky_3band_p1bm_frm"), "3band")
    merged = merge(sia, tap + tap3)
    assert len(merged) == len(sia) + len(tap3)
    assert all(f.qual_frame is not None for f in merged)
    assert [f.mjd for f in merged] == sorted(f.mjd for f in merged)
    # An SIA frame with no TAP row keeps unknown quality.
    assert all(f.qual_frame is None for f in merge(sia, []))


def test_search_frames_queries_every_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = {"allsky_4band_p1bm_frm", "allsky_3band_p1bm_frm", "allsky_2band_p1bm_frm",
              "neowiser_p1bm_frm"}
    seen = []

    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        seen.append(url)
        if url == search.SIA_URL:
            return _sia(params["COLLECTION"])
        table = next(t for t in tables if f" FROM {t} " in params["QUERY"])
        return _tap(table)

    monkeypatch.setattr(net, "get_text", fake)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert seen.count(search.SIA_URL) == 4 and seen.count(search.TAP_URL) == 4
    assert {f.phase for f in frames} == {"allsky", "3band", "postcryo", "neowiser"}
