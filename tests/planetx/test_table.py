"""The limits table: reach calculation, shape, and that the committed JSON is up to date."""

from __future__ import annotations

from pathlib import Path

from pxs.planetx import __main__ as cli
from pxs.planetx import table
from pxs.planetx.depths import Depth

ROOT = Path(__file__).resolve().parents[2]


def test_reach_picks_last_distance_still_bright_enough():
    curve = [20.0 + 0.01 * i for i, _ in enumerate(table.DISTANCES_AU)]  # fades with distance
    assert table.reach_au(curve, 20.0) == 200
    assert table.reach_au(curve, 19.0) == "<200"
    assert table.reach_au(curve, 30.0) == ">1500"
    assert table.reach_au(curve, 20.105) == table.DISTANCES_AU[10]


def test_reflected_curve_fades_by_3_mag_per_doubling_of_distance():
    case = next(c for c in table.C.CASES if c.key == "se10")
    curve = table.ab_curve(case, "SPHEREx D1", table.C.nominal)
    i300, i600 = table.DISTANCES_AU.index(300), table.DISTANCES_AU.index(600)
    assert abs(curve[i600] - curve[i300] - 2.5 * 4 * 0.30103) < 0.01


def test_fortney_curve_fades_as_distance_squared():
    c = table.fortney_curve("WISE W1", 1)
    i300, i600 = table.DISTANCES_AU.index(300), table.DISTANCES_AU.index(600)
    assert abs(c[i600] - c[i300] - 5 * 0.30103) < 0.01


def test_build_shape():
    d = Depth("x", "x", "literature", "channel", {"SPHEREx D1": (19.0, 19.5)}, "")
    out = table.build([d])
    assert {c["key"] for c in out["cases"]} == {"se5", "se10", "neptune", "jupiter"}
    se10 = next(c for c in out["cases"] if c["key"] == "se10")
    assert set(se10["reach_au"]["x"]["SPHEREx D1"]) == {"lo", "nom", "hi"}
    assert len(se10["ab"]["WISE W2"]["nom"]) == len(out["distances_au"])
    assert out["motion"]["rows"][0]["r_au"] == 200


def test_committed_json_matches_a_fresh_build():
    committed = (ROOT / "web/data/planetx-limits.json").read_text()
    assert cli.render(ROOT / "web/gallery") == committed
