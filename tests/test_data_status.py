"""tools/data_status.py: the footer's data-currency file, from the index manifest and the gallery."""

from __future__ import annotations

import json
from pathlib import Path

import data_status as ds
import pytest

MANIFEST = {
    "built_at": "2026-11-14T22:26:31+00:00", "code_version": "abc1234", "rows": 30,
    "releases": {
        "dr1": {"rows": 10, "mjd_min": 60789.5, "mjd_max": 61174.5},
        "qr3": {"rows": 20, "mjd_min": 61174.51, "mjd_max": 61318.002},
    },
}


def view(frames: list[tuple[str, str]], generated: str = "2026-11-15T12:58:35Z") -> dict:
    return {"generated": generated, "frames": [{"mission": m, "date": d} for m, d in frames]}


def test_mjd_to_date_is_utc_calendar_day() -> None:
    assert ds.mjd_to_date(61318.002) == "2026-10-05"
    assert ds.mjd_to_date(51544.99) == "2000-01-01"


def test_index_part_counts_releases_and_newest_frame() -> None:
    part = ds.index_part(MANIFEST)
    assert [r["name"] for r in part["releases"]] == ["DR1", "QR3"]
    assert [r["frames"] for r in part["releases"]] == [10, 20]
    assert part["frames_total"] == 30
    assert part["newest_frame"] == "2026-10-05"
    assert part["refreshed"] == "2026-11-14"
    assert part["code_version"] == "abc1234"


def test_index_total_must_equal_sum_of_releases() -> None:
    with pytest.raises(ValueError, match="total"):
        ds.index_part({**MANIFEST, "rows": 31})


def test_index_part_rejects_missing_fields() -> None:
    with pytest.raises(ValueError):
        ds.index_part({"releases": {}})
    with pytest.raises(ValueError):
        ds.index_part({k: v for k, v in MANIFEST.items() if k != "built_at"})


def test_gallery_part_takes_newest_spherex_only() -> None:
    views = [view([("SPHEREx", "2026-09-30T01:00:00Z"), ("WISE", "2026-12-01T00:00:00Z")]),
             view([("SPHEREx", "2026-09-12T00:00:00Z")], "2026-11-15T13:00:00Z")]
    part = ds.gallery_part(views)
    assert part["newest_frame"] == "2026-09-30"
    assert part["spherex_frames"] == 2
    assert part["views"] == 2
    assert part["built"] == "2026-11-15"


def test_gallery_part_empty_is_an_error() -> None:
    with pytest.raises(ValueError):
        ds.gallery_part([view([("WISE", "2010-02-13T00:00:00Z")])])


def test_build_status_keeps_index_and_gallery_dates_separate() -> None:
    out = ds.build_status(MANIFEST, [view([("SPHEREx", "2026-09-30T01:00:00Z")])], "2026-11-15T16:00:00Z")
    assert out["index"]["newest_frame"] == "2026-10-05"
    assert out["gallery"]["newest_frame"] == "2026-09-30"
    assert out["generated"] == "2026-11-15T16:00:00Z"
    assert "manifest.json" in out["index"]["source"]
    assert "gallery" in out["gallery"]["source"]


def test_load_gallery_reads_every_view(tmp_path: Path) -> None:
    for slug in ("a", "b"):
        (tmp_path / slug).mkdir()
        (tmp_path / slug / "manifest.json").write_text(json.dumps(view([("SPHEREx", "2026-01-02T00:00:00Z")])))
    (tmp_path / "index.json").write_text("{}")
    assert len(ds.load_gallery(tmp_path)) == 2
