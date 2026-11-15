"""The validation sample is drawn by fixed rules from SBDB answers (no network here)."""

from __future__ import annotations

from solarsystem_validation.sample import Bin, bins, build, query_params, select


def _resp(rows: list[list]) -> dict:
    return {"fields": ["spkid", "pdes", "full_name", "H", "class"], "data": rows,
            "count": len(rows)}


def test_bins_cover_every_class_and_the_mba_range():
    bs = bins()
    assert {b.cls for b in bs} == {"TNO", "CEN", "TJN", "MBA"}
    mba = [b for b in bs if b.cls == "MBA"]
    assert min(b.h_lo for b in mba) <= 5.0 and max(b.h_hi for b in mba) >= 18.0
    assert all(b.h_hi - b.h_lo == 0.5 and b.n == 2 for b in mba)


def test_query_params_ask_numbered_objects_of_the_class_in_the_range():
    p = query_params(Bin("MBA", 16.0, 16.5, 2))
    assert p["sb-class"] == "MBA" and p["sb-ns"] == "n"
    assert "H|RG|16.0|16.5" in p["sb-cdata"]
    assert int(p["limit"]) > 2  # head room for the half-open upper edge


def test_select_is_half_open_in_number_order_and_takes_n():
    rows = [[20000003, "3", "3 C", "16.5", "MBA"],  # on the upper edge: excluded
            [20000002, "2", "2 B", "16.2", "MBA"],
            [20000001, "1", "1 A", "16.0", "MBA"],
            [20000004, "4", "4 D", "16.4", "MBA"]]
    got = select(_resp(rows), Bin("MBA", 16.0, 16.5, 2))
    assert [g["pdes"] for g in got] == ["1", "2"]
    assert got[0]["H"] == 16.0 and got[0]["cls"] == "MBA" and got[0]["name"] == "1 A"


def test_select_without_n_keeps_all_and_without_lower_edge():
    rows = [[20090377, "90377", " 90377 Sedna (2003 VB12)", "1.50", "TNO"],
            [20134340, "134340", "134340 Pluto (1930 BM)", "-0.55", "TNO"]]
    got = select(_resp(rows), Bin("TNO", None, 4.0, None))
    assert [g["pdes"] for g in got] == ["90377", "134340"]
    assert got[0]["name"] == "90377 Sedna (2003 VB12)"


def test_build_records_queries_raw_answers_and_bodies():
    calls = []

    def fetch(params: dict) -> dict:
        calls.append(params)
        return _resp([[20000001, "1", "1 A", "16.1", params["sb-class"]]])

    out = build(fetch, [Bin("MBA", 16.0, 16.5, 1), Bin("CEN", None, None, 1)], "2026-11-14")
    assert out["drawn_utc"] == "2026-11-14" and len(calls) == 2
    assert [b["params"] for b in out["bins"]] == calls
    assert all("response" in b for b in out["bins"])
    assert [b["cls"] for b in out["bodies"]] == ["MBA", "CEN"]
