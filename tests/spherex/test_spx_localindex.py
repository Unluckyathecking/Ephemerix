"""Coverage test, incremental indexing and the SIA fallback, all offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from spherex_index import build_index as bi

from pxs.spherex import config, localindex, query
from pxs.spherex.indexfmt import UnreadableFrame, parse_frame, rebuild_key
from pxs.spherex.localindex import FrameIndex, IndexUnavailable

from .conftest import FIXTURES
from .index_helpers import fake_file, fake_row, image_hdr, sky_at

# ---- building small indexes on disk --------------------------------------------------------


def build(root: Path, rows: list[dict]) -> Path:
    by_week: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_week.setdefault((r["release"], r["week"]), []).append(r)
    for (rel, wk), rs in by_week.items():
        bi.write_part(root, rel, wk, rs)
    bi.write_manifest(root, "test")
    return root


def frame_at(ra: float, dec: float, n: int = 0, **kw) -> dict:
    return fake_row(ra, dec, obs=f"2025W17_4B_{n:04d}_1", mjd=60790.0 + n, **kw)


def rect_edge_sky(row: dict, x: float, y: float) -> tuple[float, float]:
    """Sky position of pixel (x, y) of a fake frame, from astropy."""
    hdr = image_hdr()
    hdr["CRVAL1"], hdr["CRVAL2"], hdr["LATPOLE"] = row["crval1"], row["crval2"], row["crval2"]
    return sky_at(hdr, x, y)


# ---- exact coverage ------------------------------------------------------------------------


def test_point_inside_and_outside(tmp_path: Path) -> None:
    idx = FrameIndex.load(build(tmp_path, [frame_at(160.6, 30.7)]))
    assert len(idx.find([(160.6, 30.7)], 0.0005)) == 1
    assert idx.find([(160.6, 34.0)], 0.0005) == []  # 3.3 deg off
    assert idx.find([(340.6, -30.7)], 0.0005) == []  # antipode


def test_edges_are_exact_not_a_centre_distance_cut(tmp_path: Path) -> None:
    row = frame_at(160.6, 30.7)
    idx = FrameIndex.load(build(tmp_path, [row]))
    inside = rect_edge_sky(row, 3.0, 1020.5)  # 2.5 px from the left edge
    outside = rect_edge_sky(row, -3.0, 1020.5)  # 3.5 px beyond it
    assert len(idx.find([inside], 0.0001)) == 1
    assert idx.find([outside], 0.0001) == []
    # a circle of 5 px (30 arcsec) reaches back onto the image; the margin grows it too
    assert len(idx.find([outside], 5 * 6.15 / 3600)) == 1
    assert len(idx.find([outside], 0.0001, margin_px=5.0)) == 1
    # corners are rounded, not squares: the diagonal point 4 px out in x and y is 5.7 px away
    diag = rect_edge_sky(row, -3.5, -3.5)
    assert idx.find([diag], 5 * 6.15 / 3600) == []
    assert len(idx.find([diag], 6 * 6.15 / 3600)) == 1


def test_footprint_across_ra_zero(tmp_path: Path) -> None:
    idx = FrameIndex.load(build(tmp_path, [frame_at(359.95, 10.0)]))
    assert len(idx.find([(0.5, 10.0)], 0.0005)) == 1
    assert len(idx.find([(359.0, 10.0)], 0.0005)) == 1
    assert idx.find([(3.0, 10.0)], 0.0005) == []
    assert idx.find([(356.5, 10.0)], 0.0005) == []


@pytest.mark.parametrize("dec0", [89.2, -89.2])
def test_footprint_near_the_poles(tmp_path: Path, dec0: float) -> None:
    row = frame_at(40.0, dec0)
    idx = FrameIndex.load(build(tmp_path, [row]))
    sign = 1 if dec0 > 0 else -1
    # the pole itself is 0.8 deg from the centre: inside, at any RA
    assert len(idx.find([(0.0, sign * 90.0)], 0.0005)) == 1
    assert len(idx.find([(200.0, sign * 89.9)], 0.0005)) == 1
    assert idx.find([(40.0, sign * 85.0)], 0.0005) == []
    assert idx.find([(220.0, sign * 86.0)], 0.0005) == []
    # every astropy pixel position near the edges comes back, all around the frame
    for x, y in [(30, 1020), (2010, 1020), (1020, 30), (1020, 2010)]:
        assert len(idx.find([rect_edge_sky(row, x, y)], 0.0001)) == 1


def test_matches_astropy_on_a_random_sky(tmp_path: Path) -> None:
    """Coverage decided by pixel limits in astropy's own WCS equals the index's answer."""
    row = frame_at(100.0, 5.0)
    idx = FrameIndex.load(build(tmp_path, [row]))
    rng = np.random.default_rng(3)
    for px, py in rng.uniform(-300, 2340, size=(200, 2)):
        inside = 0.5 <= px <= 2040.5 and 0.5 <= py <= 2040.5
        near_edge = min(abs(px - 0.5), abs(px - 2040.5), abs(py - 0.5), abs(py - 2040.5)) < 0.5
        if near_edge and inside == (0.5 <= px <= 2040.5 and 0.5 <= py <= 2040.5):
            continue  # within SIP-inverse accuracy of the boundary; not a meaningful check
        got = len(idx.find([rect_edge_sky(row, px, py)], 1e-6)) == 1
        assert got == inside, (px, py)


def test_frames_have_the_find_frames_fields(tmp_path: Path) -> None:
    deep = fake_row(250.0, 66.0, obs="2025W17_4B_0021_1", det=3, sps="deep_north", mjd=60789.88)
    idx = FrameIndex.load(build(tmp_path, [deep, frame_at(250.0, 66.0, 5, det=6)]))
    both = idx.find([(250.0, 66.0)], 0.0005, ("spherex_dr1", "spherex_dr1_deep"))
    assert [(f.collection, f.detector) for f in both] == [("spherex_dr1_deep", 3),
                                                          ("spherex_dr1", 6)]
    d = both[0]
    assert d.s3_key == rebuild_key("dr1", "2025W17_4B", "l2b-v27-2026-196", d.obs_id, 3)
    assert (d.em_min_um, d.em_max_um) == (1.6301, 2.4346)
    assert [f.collection for f in idx.find([(250.0, 66.0)], 0.0005, ("spherex_dr1",))] == [
        "spherex_dr1"]
    assert idx.find([(250.0, 66.0)], 0.0005, ("spherex_qr3",)) == []


def test_path_of_positions_is_the_union(tmp_path: Path) -> None:
    idx = FrameIndex.load(build(tmp_path, [frame_at(10.0, 0.0, 1), frame_at(80.0, 0.0, 2)]))
    path = [(10.0, 0.0), (45.0, 0.0), (80.0, 0.0), (10.0, 0.1)]
    assert [f.obs_id for f in idx.find(path, 0.0005)] == ["2025W17_4B_0001_1",
                                                          "2025W17_4B_0002_1"]


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(IndexUnavailable):
        FrameIndex.load(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 999}))
    with pytest.raises(IndexUnavailable, match="schema"):
        FrameIndex.load(tmp_path)


# ---- the consolidated cache ----------------------------------------------------------------

PROBES = [(160.6, 30.7), (250.0, 66.0), (331.0, -56.8), (10.0, 0.0), (0.0, 89.9)]
BOTH = ("spherex_dr1", "spherex_dr1_deep", "spherex_qr3", "spherex_qr3_deep")


def mixed_rows() -> list[dict]:
    return [frame_at(160.6, 30.7, 1),
            fake_row(250.0, 66.0, obs="2025W17_4B_0021_1", det=3, sps="deep_north"),
            fake_row(331.0, -56.8, obs="2026W40_2A_0001_3", week="2026W40_2A", release="qr3",
                     det=5, mjd=61300.0),
            fake_row(160.6, 30.7, obs="2026W40_2A_0002_3", week="2026W40_2A", release="qr3",
                     det=2, mjd=61301.0)]


def answers(idx: FrameIndex) -> list[list]:
    return [idx.find([p], 0.01, BOTH) for p in PROBES]


def test_cache_round_trip_gives_identical_lookups(tmp_path: Path) -> None:
    root = build(tmp_path, mixed_rows())
    parquet = FrameIndex.load(root)
    path = localindex.write_cache(root)
    assert path == root / localindex.CACHE_NAME and path.exists()
    cached = FrameIndex.load(root)
    assert cached.from_cache and not parquet.from_cache
    assert len(cached) == len(parquet) == 4
    assert answers(cached) == answers(parquet)
    assert sum(len(a) for a in answers(cached)) == 4


def test_stale_cache_is_ignored(tmp_path: Path) -> None:
    root = build(tmp_path, mixed_rows())
    localindex.write_cache(root)
    build(root, [frame_at(10.0, 0.0, 9)])  # new shard and a rewritten manifest
    idx = FrameIndex.load(root)
    assert not idx.from_cache and len(idx) == 5
    assert [f.obs_id for f in idx.find([(10.0, 0.0)], 0.01)] == ["2025W17_4B_0009_1"]


@pytest.mark.parametrize("damage", ["garbage", "empty", "truncated"])
def test_corrupt_cache_falls_back_to_parquet(tmp_path: Path, damage: str) -> None:
    root = build(tmp_path, mixed_rows())
    expected = answers(FrameIndex.load(root))
    path = localindex.write_cache(root)
    good = path.read_bytes()
    path.write_bytes({"garbage": b"garbage", "empty": b"", "truncated": good[:len(good) // 2]}[
        damage])
    idx = FrameIndex.load(root)
    assert not idx.from_cache and answers(idx) == expected


def test_build_cache_cli(tmp_path: Path) -> None:
    root = build(tmp_path, mixed_rows())
    localindex.main(["--build-cache", str(root)])
    assert FrameIndex.load(root).from_cache


# ---- incremental indexing ------------------------------------------------------------------


class FakeFetcher:
    """Stands in for build_index.Fetcher: a listing plus the files' leading bytes."""

    listing: ClassVar[list[tuple[str, int]]] = []
    files: ClassVar[dict[str, bytes]] = {}
    reads: ClassVar[list[str]] = []

    def __init__(self, max_rps: float, counters: bi.Counters) -> None:
        self.c = counters

    def list_prefix(self, prefix: str, delimiter: str | None = None):
        return list(FakeFetcher.listing), []

    def header_row(self, key: str, size: int) -> dict:
        FakeFetcher.reads.append(key)
        return parse_frame(key, size, FakeFetcher.files[key])


def key_for(n: int) -> str:
    return rebuild_key("dr1", "2025W17_4B", "l2b-v27-2026-196", f"2025W17_4B_{n:04d}_1", 1)


@pytest.fixture
def fake_bucket(monkeypatch: pytest.MonkeyPatch) -> type[FakeFetcher]:
    monkeypatch.setattr(bi, "Fetcher", FakeFetcher)
    FakeFetcher.reads = []
    FakeFetcher.files = {key_for(n): fake_file(10.0 + n, 5.0, obs=f"2025W17_4B_{n:04d}_1")
                         for n in range(1, 6)}
    FakeFetcher.files[key_for(3)] = b"garbage"
    FakeFetcher.listing = [(key_for(n), 100) for n in (1, 2, 3)]
    return FakeFetcher


def test_incremental_indexing_reads_only_new_keys(tmp_path: Path, fake_bucket) -> None:
    c1 = bi.index_week(tmp_path, "dr1", "2025W17_4B", chunk=2)
    assert (c1.rows, c1.failed, c1.skipped) == (2, 1, 0)
    assert len(list(tmp_path.glob("rows/*/*/part-*.parquet"))) == 1  # chunk with a row only
    failed = json.loads((tmp_path / "failed/dr1/2025W17_4B.json").read_text())
    assert [f["key"] for f in failed] == [key_for(3)]

    fake_bucket.reads.clear()
    fake_bucket.listing += [(key_for(4), 100), (key_for(5), 100)]
    c2 = bi.index_week(tmp_path, "dr1", "2025W17_4B", chunk=2)
    assert sorted(fake_bucket.reads) == [key_for(3), key_for(4), key_for(5)]  # failure retried
    assert (c2.rows, c2.skipped, c2.failed) == (2, 2, 1)

    fake_bucket.reads.clear()
    fake_bucket.files[key_for(3)] = fake_file(13.0, 5.0, obs="2025W17_4B_0003_1")
    c3 = bi.index_week(tmp_path, "dr1", "2025W17_4B", chunk=2)
    assert fake_bucket.reads == [key_for(3)] and (c3.rows, c3.failed) == (1, 0)
    assert not (tmp_path / "failed/dr1/2025W17_4B.json").exists()

    fake_bucket.reads.clear()
    c4 = bi.index_week(tmp_path, "dr1", "2025W17_4B")  # idempotent: nothing to do
    assert fake_bucket.reads == [] and (c4.rows, c4.skipped) == (0, 5)
    m = bi.write_manifest(tmp_path, "v")
    assert m["rows"] == 5 and m["releases"]["dr1"]["weeks"] == 1 and m["failed"] == 0


def test_rewriting_the_same_rows_does_not_duplicate(tmp_path: Path) -> None:
    rows = [frame_at(10.0, 0.0, 1), frame_at(11.0, 0.0, 2)]
    bi.write_part(tmp_path, "dr1", "2025W17_4B", rows)
    bi.write_part(tmp_path, "dr1", "2025W17_4B", list(reversed(rows)))
    assert len(list(tmp_path.glob("rows/*/*/part-*.parquet"))) == 1


def test_unreadable_helper_raises_for_bad_bytes() -> None:
    with pytest.raises(UnreadableFrame):
        parse_frame(key_for(1), 1, b"nope")


# ---- fallback in query.find_frames ---------------------------------------------------------


@pytest.fixture
def sia_log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(coll: str, ra: float, dec: float, radius: float, **_kw) -> bytes:
        calls.append(coll)
        return (FIXTURES / "sia_eps_ind_b_dr1.xml").read_bytes()

    monkeypatch.setattr(query, "_sia_bytes", fake)
    monkeypatch.delenv(localindex.ENV_DIR, raising=False)
    monkeypatch.delenv(localindex.ENV_TAIL, raising=False)
    localindex.clear_cache()
    return calls


def test_without_an_index_sia_is_used(sia_log: list[str]) -> None:
    assert len(query.find_frames(331.0, -56.8, collections=("spherex_dr1",))) == 10
    assert sia_log == ["spherex_dr1"]


def test_index_answers_without_sia(tmp_path: Path, sia_log, monkeypatch) -> None:
    build(tmp_path, [frame_at(331.0, -56.8, 1)])
    monkeypatch.setenv(localindex.ENV_DIR, str(tmp_path))
    out = query.find_frames(331.0, -56.8, collections=("spherex_dr1",))
    assert [f.obs_id for f in out] == ["2025W17_4B_0001_1"] and sia_log == []


@pytest.mark.parametrize("case", ["missing_dir", "no_manifest", "stale_release", "lookup_error"])
def test_every_failure_falls_back_to_sia(tmp_path: Path, sia_log, monkeypatch, case) -> None:
    build(tmp_path / "ok", [frame_at(331.0, -56.8, 1)])
    target = {"missing_dir": tmp_path / "nope", "no_manifest": tmp_path,
              "stale_release": tmp_path / "ok", "lookup_error": tmp_path / "ok"}[case]
    monkeypatch.setenv(localindex.ENV_DIR, str(target))
    colls = ("spherex_dr1", "spherex_qr3") if case == "stale_release" else ("spherex_dr1",)
    if case == "lookup_error":
        def boom(*a, **k):
            raise RuntimeError("bug")
        monkeypatch.setattr(FrameIndex, "find", boom)
    out = query.find_frames(331.0, -56.8, collections=colls)
    assert len(out) == 10 * len(colls) and sia_log == list(colls)


def test_sia_tail_adds_only_frames_newer_than_the_index(tmp_path: Path, sia_log,
                                                         monkeypatch) -> None:
    sia_frames = query.parse_votable((FIXTURES / "sia_eps_ind_b_dr1.xml").read_bytes(),
                                     "spherex_dr1")
    cut = sorted(f.mjd for f in sia_frames)[4]  # the index knows the oldest 5 (mjd <= cut)
    old = fake_row(331.0, -56.8, obs="2025W17_4B_0001_1", mjd=cut)
    build(tmp_path, [old])
    monkeypatch.setenv(localindex.ENV_DIR, str(tmp_path))
    monkeypatch.setenv(localindex.ENV_TAIL, "1")
    out = query.find_frames(331.0, -56.8, collections=("spherex_dr1",))
    assert sia_log == ["spherex_dr1"]
    assert len(out) == 1 + sum(f.mjd > cut for f in sia_frames) == 6
    assert out[0].obs_id == "2025W17_4B_0001_1"
    # if SIA is down in tail mode, the index alone still answers
    monkeypatch.setattr(query, "_sia_bytes", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert [f.obs_id for f in query.find_frames(331.0, -56.8, collections=("spherex_dr1",))] == [
        "2025W17_4B_0001_1"]


def test_releases_come_from_config() -> None:
    assert bi.releases() == tuple(c.removeprefix("spherex_") for c in config.COLLECTIONS)
