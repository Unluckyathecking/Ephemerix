"""Small offline checks: geometry, limits, false-alarm arithmetic, JPL parsers, JSON."""

from __future__ import annotations

import json
import math

import numpy as np

from pxs.movers.ephem import parse_horizons, parse_sbident
from pxs.movers.field import MAX_SPAN_DAYS, reference_frames, search_window
from pxs.movers.geometry import MAX_POS_ERR_PX, distance_grid, pass_geometry, trajectory_grid
from pxs.movers.limits import (
    absolute_mag,
    motion_distance,
    reflected_distance,
    thermal_distance,
    vmag_from_1um,
)
from pxs.movers.result import SearchResult
from pxs.movers.search import make_trials, track_span_px
from pxs.movers.vet import expected_false, false_alarm_probability
from pxs.spherex.types import Frame, Pass


def _geom():
    mjd = np.linspace(60846.0, 60856.0, 40)
    return pass_geometry(218.6, 15.0, mjd, 6.15)


def test_geometry_reflex_matches_haumea_order_of_magnitude() -> None:
    g = _geom()
    # Haumea (49.5 au) moved 5.25, 3.19 px/day by Horizons in this field and pass.
    v = g.reflex_px_day / 49.5
    assert 4.5 < v[0] < 7.5 and 1.5 < v[1] < 4.5
    # Curvature (at 1 au) vanishes at mid-pass to first order in |dt| <= 0.13 d.
    assert np.allclose(g.curve_px[:, np.argmin(np.abs(g.dt))], 0, atol=0.2)


def test_distance_grid_spacing_bounds_curvature_error() -> None:
    g = _geom()
    ds = distance_grid(g)
    cmax = np.max(np.hypot(*g.curve_px))
    gaps = np.diff(np.sort(1 / ds))
    assert np.all(gaps * cmax <= 2 * MAX_POS_ERR_PX + 1e-9)
    assert ds.min() >= 30 and ds.max() <= 1000


def test_trials_exclude_static_and_are_unique() -> None:
    g = _geom()
    tr = make_trials(g, trajectory_grid(g))
    assert np.all(track_span_px(tr.offsets.astype(float)) >= 1.0)
    flat = tr.offsets.reshape(len(tr), -1)
    assert len(np.unique(flat, axis=0)) == len(tr)


def test_limits_arithmetic() -> None:
    # next-phase.md A2: R 3.5 R_E, p 0.4 -> H = -6.6 (D = 44,600 km).
    assert abs(absolute_mag(3.5, 0.4) - (-6.6)) < 0.05
    assert abs(reflected_distance(19.7, 3.5, 0.4) - 430) < 15
    assert abs(thermal_distance(38.0, 112.0) - 1068) < 5
    assert 18.5 < vmag_from_1um(150.0) < 19.5  # Eris: ~155 uJy at 0.9 um for V 18.7
    assert motion_distance(_geom(), 1.5) > 100


def test_false_alarm_extrapolation() -> None:
    null = [5.1, 5.2, 5.5, 6.0]
    assert expected_false(5.0, null) >= 4
    assert expected_false(12.0, null) < 1e-10
    assert 0 < false_alarm_probability(7.0, null) < 0.05


def test_reference_frames_skip_close_passes() -> None:
    def f(m: float, det: int = 1) -> Frame:
        return Frame("c", f"o{m}", det, m, f"k{m}", 0.75, 1.1)

    a, b, c = Pass((f(100), f(101))), Pass((f(130),)), Pass((f(300), f(301, 4)))
    frames, n = reference_frames([a, b, c], a, (1, 2, 3))
    assert n == 1 and [x.mjd for x in frames] == [300]


def test_parse_horizons_and_sbident() -> None:
    body = (" 2460850.500000000, , ,  218.43970,  14.74950,   17.288,  n.a., 49.9, 0.1, "
            "49.45, 1.0, 100.0,/L,")
    text = json.dumps({"result": f"header\n$$SOE\n{body}\n$$EOE\n"})
    (r,) = parse_horizons(text)
    assert math.isclose(r.mjd, 60850.0) and math.isclose(r.ra, 218.4397)
    assert math.isclose(r.vmag, 17.288) and math.isclose(r.delta_au, 49.45)
    sb = {"fields_first": ["Object name", "Astrometric RA (hh:mm:ss)",
                           "Astrometric Dec (dd mm'ss\")", "Visual magnitude (V)",
                           "RA rate (\"/h)", "Dec rate (\"/h)"],
          "data_first_pass": [["136108 Haumea", "14:33:45", "+14 44'58\"", "17.3", "1.2",
                               "-0.5"]]}
    (o,) = parse_sbident(json.dumps(sb))
    assert abs(o.ra - 218.4375) < 1e-6 and abs(o.dec - 14.749444) < 1e-5
    assert o.name.endswith("Haumea") and o.vmag == 17.3


def test_result_json_is_strict() -> None:
    r = SearchResult(1.0, 2.0, 20.0, (1.0, 2.0), 10, 20, 2, 0.1, 100, 7.0, 1.5, [], 0,
                     float("nan"), {"read": 1.0})
    d = r.to_json()
    s = json.dumps(d, allow_nan=False)
    assert d["null_max_snr"] is None and '"schema_version": 1' in s


def test_trial_count_grows_steeply_with_pass_span() -> None:
    # dv shrinks as 1/span and the distance nodes grow as span^2, so trials go as ~span^4.
    def n(span: float) -> int:
        g = pass_geometry(218.6, 15.0, np.linspace(60846.0, 60846.0 + span, 40), 6.15)
        return len(make_trials(g, trajectory_grid(g)))

    n9, n18 = n(9.0), n(18.0)
    assert n18 > 8 * n9
    assert n(MAX_SPAN_DAYS) < 100_000  # keeps one search near 2-3 min on one core


def test_search_window_keeps_densest_span_within_cap() -> None:
    def f(m: float) -> Frame:
        return Frame("c", f"o{m}", 1, m, f"k{m}", 0.75, 1.1)

    # Frame times of the B1 field's pass (44 days, gaps up to 10 days), 4 frames a visit.
    visits = [0.0, 1.56, 3.8, 6.59, 13.66, 23.85, 34.04, 42.12, 43.82]
    frames = [f(60700 + v + 0.01 * k) for v in visits for k in range(4)]
    kept = search_window(frames)
    span = kept[-1].mjd - kept[0].mjd
    assert span <= MAX_SPAN_DAYS
    assert [round(x.mjd - 60700, 2) for x in kept[::4]] == [0.0, 1.56, 3.8, 6.59, 13.66]
    short = frames[:8]
    assert search_window(short) == short


def test_merge_units_joins_base_and_runs(tmp_path) -> None:
    from pxs.movers.campaign import merge_units

    np.savez(tmp_path / "F__base.npz", X=np.zeros((2, 4, 15, 15)), F=np.zeros((2, 8)),
             Y=np.array([0, 2]), S=np.array([5.0, 9.0]), R=np.array(["real", "null"]))
    (tmp_path / "F__base.json").write_text(json.dumps({"total_s": 1.0}))
    for r in range(2):
        np.savez(tmp_path / f"F__run{r:02d}.npz", X=np.zeros((1, 4, 15, 15)),
                 F=np.zeros((1, 8)), Y=np.array([1]), S=np.array([8.0]), R=np.array(["inj"]),
                 inj_flux=np.ones(3), inj_rate=np.ones(3), inj_d=np.ones(3),
                 inj_rec=np.array([1, 0, 1], bool), inj_pos=np.ones(3, bool),
                 inj_snr=np.ones(3), extras=np.array([r]))
        (tmp_path / f"F__run{r:02d}.json").write_text(json.dumps(
            {"total_s": 2.0, "n_injected": 3, "n_recovered": 2, "n_at_position": 3,
             "extras": [r]}))
    assert merge_units(tmp_path, tmp_path / "out") == ["F"]
    z = np.load(tmp_path / "out" / "F.npz")
    assert z["Y"].tolist() == [0, 2, 1, 1] and z["inj_rec"].sum() == 4
    meta = json.loads((tmp_path / "out" / "F.json").read_text())
    assert meta["n_runs"] == 2 and meta["n_injected"] == 6 and meta["extras_per_run"] == [0, 1]
