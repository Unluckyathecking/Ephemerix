import dataclasses

import pytest
from conftest import GRID, make_frame, make_wcs

from pxs.wise import visits as visits_mod
from pxs.wise.geometry import covers_grid, edge_distance_arcsec
from pxs.wise.select import choose_frames
from pxs.wise.visits import find_visits, group_visits, path_from_motion

RA, DEC = GRID.center_ra, GRID.center_dec


def _at(f, mjd):
    return dataclasses.replace(f, mjd=mjd)


def test_edge_distance_inside_and_outside() -> None:
    corners = make_frame(0, make_wcs(RA, DEC, 30.0, 100)).corners  # 275" square
    assert edge_distance_arcsec(corners, RA, DEC) == pytest.approx(136.125, abs=0.01)
    assert edge_distance_arcsec(corners, RA, DEC + 0.1) < 0
    assert covers_grid(corners, GRID)
    assert not covers_grid(make_frame(1, make_wcs(RA + 0.04, DEC, 0.0, 100)).corners, GRID)


def test_group_visits_splits_on_gaps_and_long_runs() -> None:
    f = make_frame(0, make_wcs(RA, DEC, 0, 100))
    six_monthly = [_at(f, 55300 + 182 * k + d) for k in range(3) for d in (0.0, 0.5, 1.2)]
    assert [len(g) for g in group_visits(six_monthly)] == [3, 3, 3]
    # Continuous coverage (ecliptic pole): every 10 days for 2 years -> half-year bins.
    pole = [_at(f, 58119.0 + 10 * k) for k in range(73)]  # 58119 = 2018.0
    groups = group_visits(pole)
    assert len(groups) == 4
    assert all(g[-1].mjd - g[0].mjd < 183 for g in groups)


def _fake_search(frames):
    return lambda ra, dec, radius, workers=4: list(frames)


def test_find_visits_drops_qual0_and_frames_off_target(monkeypatch: pytest.MonkeyPatch) -> None:
    good = make_frame(0, make_wcs(RA, DEC, 10, 400))
    bad_quality = make_frame(1, make_wcs(RA, DEC, 10, 400), qual=0)
    target_at_edge = make_frame(2, make_wcs(RA + 0.161, DEC, 0, 400))  # 5" from edge
    later = _at(make_frame(3, make_wcs(RA, DEC, 10, 400)), 58200.0)
    monkeypatch.setattr(visits_mod, "search_frames",
                        _fake_search([good, bad_quality, target_at_edge, later]))
    found = find_visits(RA, DEC)
    assert [v.frames for v in found] == [(good,), (later,)]
    assert found[0].bands == ("W2",) and found[0].target_ra == pytest.approx(RA)


def test_find_visits_follows_a_moving_target(monkeypatch: pytest.MonkeyPatch) -> None:
    # Moves 0.2 deg north per year; one small frame per epoch at the right place.
    path = path_from_motion(RA, DEC, 2015.0, 0.0, 720000.0, 2014.0, 2016.1)
    early = make_frame(0, make_wcs(RA, DEC - 0.2, 0, 200), mjd=56658.75)  # 2014.0
    late = make_frame(1, make_wcs(RA, DEC + 0.2, 0, 200), mjd=57388.5)  # 2016.0
    wrong = make_frame(2, make_wcs(RA, DEC + 0.2, 0, 200), mjd=56659.75)  # covers 2016 spot
    monkeypatch.setattr(visits_mod, "search_frames", _fake_search([early, wrong, late]))
    found = find_visits(RA, DEC, path=path)
    assert [v.frames for v in found] == [(early,), (late,)]
    assert found[0].target_dec == pytest.approx(DEC - 0.2, abs=1e-3)


@pytest.mark.parametrize("args", [(360.0, 0.0), (10.0, 91.0), (10.0, 0.0, 0.0),
                                  (float("nan"), 0.0)])
def test_find_visits_validates_inputs(args) -> None:
    with pytest.raises(ValueError):
        find_visits(*args)


def test_cap_picks_by_quality_then_coverage() -> None:
    w_in, w_off = make_wcs(RA, DEC, 0, 400), make_wcs(RA + 0.1, DEC, 0, 400)
    frames = ([make_frame(i, w_in, qual=5) for i in range(5)]
              + [make_frame(10 + i, w_off, qual=10) for i in range(3)]
              + [make_frame(20 + i, w_in, qual=10) for i in range(3)]
              + [make_frame(30, w_in, qual=None), make_frame(31, w_in, qual=0)])
    chosen = choose_frames(frames, GRID, RA, DEC, max_frames=7)
    nums = [f.frame_num for f in chosen]
    # qual 10 first (full-grid coverage before partial), then qual 5; unknown and 0 never here.
    assert nums[:3] == [20, 21, 22] and set(nums[3:6]) == {10, 11, 12}
    assert set(nums[6:]) <= {0, 1, 2, 3, 4}
    assert 31 not in [f.frame_num for f in choose_frames(frames, GRID, RA, DEC, 99)]
    with pytest.raises(ValueError):
        choose_frames(frames, GRID, RA, DEC, 0)
