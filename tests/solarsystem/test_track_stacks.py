"""Track search planning, controls sampling, photometry of synthetic stamps and the stacks."""

from __future__ import annotations

import numpy as np
import pytest

from pxs.solarsystem import controls, track
from pxs.solarsystem.phot import band_flux, measure_pass
from pxs.solarsystem.stacks import body_centred, read_half, short_windows, sky_fixed
from pxs.solarsystem.track import Query, Visit, merge_daily, plan_queries, visible
from pxs.spherex import config

from .conftest import eph, frame, make_stamp, measured

RA0, DEC0 = 221.0, 13.7
ARCSEC = 1 / 3600


def test_visible_and_queries_cover_slow_body():
    days = [eph(61000.0 + i, RA0 + i * 1e-2, DEC0, rate=1.5) for i in range(12)]
    days = [type(d)(**{**d.__dict__, "elong_deg": 70.0 if i < 2 else 95.0})
            for i, d in enumerate(days)]
    vis = visible(days)
    assert len(vis) == 10
    q = merge_daily(plan_queries(vis))
    assert len(q) == 2  # 10 contiguous days -> two 5-day cones
    assert q[0].mjd_lo == pytest.approx(61001.5) and q[-1].mjd_hi == pytest.approx(61011.5)
    for c in q:  # every daily position is inside its cone
        for d in vis:
            if c.mjd_lo <= d.mjd < c.mjd_hi:
                sep = np.hypot((d.ra - c.ra) * np.cos(np.radians(DEC0)), d.dec - c.dec)
                assert sep < c.radius_deg


def test_fast_mover_gets_short_steps():
    q = plan_queries([eph(61000.0, RA0, DEC0, rate=150.0)])  # 1 deg/day
    assert len(q) == 1 and q[0].radius_deg <= 1.0 and q[0].radius_deg > 0.5
    assert merge_daily(q) == [Query(q[0].ra, q[0].dec, q[0].radius_deg, q[0].mjd_lo,
                                    q[0].mjd_hi)]


def test_frames_for_keeps_only_frames_in_the_cone_window(monkeypatch):
    fs = [frame(61000.2), frame(61003.0), frame(61000.4, det=2)]
    monkeypatch.setattr(track, "find_frames", lambda ra, dec, r, c=None: fs)
    got, failed = track.frames_for([Query(RA0, DEC0, 0.1, 61000.0, 61001.0)])
    assert [f.mjd for f in got] == [61000.2, 61000.4] and failed == 0


def test_failed_cone_is_counted(monkeypatch):
    def boom(ra, dec, r, c=None):
        raise RuntimeError("every SIA query failed")
    monkeypatch.setattr(track, "find_frames", boom)
    monkeypatch.setattr(track, "SIA_PAUSE_S", 0.0)
    assert track.frames_for([Query(RA0, DEC0, 0.1, 61000.0, 61001.0)]) == ([], 1)


def test_passes_and_control_sampling():
    vs = [Visit(frame(m), eph(m, RA0, DEC0)) for m in (61000.0, 61001.0, 61050.0, 61090.0)]
    groups = track.passes_of(vs)
    assert [len(g[1]) for g in groups] == [2, 1, 1]
    pts = controls.sample_track(vs, 3)
    assert [p.mjd for p in pts] == [61000.0, 61050.0, 61090.0]


def test_control_frames_exclude_the_pass(monkeypatch):
    fs = [frame(m, det=d) for m in (60800.0, 61000.5, 61200.0, 61210.0, 61220.0, 61230.0)
          for d in (1, 2)]
    monkeypatch.setattr(track, "find_frames", lambda ra, dec, r, c: fs if c == ("spherex_dr1",) else [])
    got = controls.control_frames(eph(61000.0, RA0, DEC0), 61000.0, 61001.0, per_detector=2)
    assert all(not (60998 <= f.mjd <= 61003) for f in got)
    assert sorted(f.detector for f in got) == [1, 1, 2, 2]


def test_photometry_recovers_injected_flux():
    read = [(Visit(frame(61000.0 + i * 0.1, key=f"k{i}"), eph(61000.0 + i * 0.1, RA0, DEC0)),
             make_stamp(RA0, DEC0, 61000.0 + i * 0.1, 0.9, 0.5, seed=i)) for i in range(12)]
    ms = measure_pass(read)
    assert len(ms) == 12
    b = band_flux([m.point for m in ms], "spx-b1")
    assert b.flux_mjy == pytest.approx(0.5, abs=5 * b.err_mjy)
    assert b.snr > 50


def _moving(n: int, rate_arcsec_day: float, flux: float = 1.0) -> list:
    out = []
    for i in range(n):
        mjd = 61000.0 + i
        ra = RA0 + i * rate_arcsec_day * ARCSEC / np.cos(np.radians(DEC0))
        out.append(measured(mjd, ra, DEC0, 0.9, flux, half=read_half(), seed=i))
    return out


def test_body_centred_stack_keeps_body_at_centre():
    st = body_centred(_moving(4, 30.0), "spx-b1", (0.75, 1.10))
    assert st is not None and st.n_exposures == 4
    y, x = np.unravel_index(np.nanargmax(st.image), st.image.shape)
    c = st.image.shape[0] / 2
    assert abs(x + 0.5 - c) <= 2 and abs(y + 0.5 - c) <= 2
    assert body_centred(_moving(2, 30.0), "spx-b3", (1.65, 2.42)) is None


def test_short_windows_limit_smear():
    ms = _moving(6, 4.0)  # 4 arcsec/day: 0.65 px per day
    groups = short_windows(ms)
    assert [len(g) for g in groups] == [2, 2, 2]


def test_sky_fixed_flipbook_shows_motion():
    sky = sky_fixed(_moving(5, 20.0), "spx-b1", (0.75, 1.10))
    assert sky is not None and len(sky.stacks) == 5
    xs = [p[0] for p in sky.body_px]
    assert xs == sorted(xs, reverse=True)  # moving east = towards the left
    assert sky.track_arcsec == pytest.approx(80.0, rel=0.02)
    for st, (x, y) in zip(sky.stacks, sky.body_px):
        yy, xx = np.unravel_index(np.nanargmax(st.image), st.image.shape)
        assert abs(xx + 0.5 - x) <= 2 and abs(yy + 0.5 - y) <= 2
    assert sky_fixed(_moving(3, 1.0), "spx-b1", (0.75, 1.10)) is None  # under 2 px of motion


def test_read_half_covers_both_grids():
    assert read_half() * config.PIXSCALE_ARCSEC > 180 * np.sqrt(2) / 2 + 0.3 * 180


def test_outlier_flag_is_cleared_only_at_the_body():
    from pxs.solarsystem.phot import OUTLIER_BIT, unflag_outlier
    s = make_stamp(RA0, DEC0, 61000.0, 0.9, 0.5)
    n = s.flags.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    flagged = np.where(np.hypot(xx - n // 2, yy - n // 2) <= 3, OUTLIER_BIT, 0).astype(np.int32)
    flagged[0, 0] = OUTLIER_BIT
    flagged.setflags(write=False)
    from dataclasses import replace
    s2 = replace(s, flags=flagged)
    out = unflag_outlier(s2)
    c = s.flags.shape[0] // 2
    assert out.flags[c, c] == 0 and out.flags[0, 0] == OUTLIER_BIT
    assert s2.flags[c, c] == OUTLIER_BIT  # input untouched
    ms = measure_pass([(Visit(frame(61000.0), eph(61000.0, RA0, DEC0)), s2)])
    assert not ms[0].point.flagged
    from pxs.spherex.photometry import measure
    assert not measure(s2).ok  # without the fix the body is masked


class FakeIndex:
    """FrameIndex stand-in: returns `frames` for any lookup and records the calls."""

    releases: frozenset = frozenset({"dr1", "qr3"})

    def __init__(self, frames, end: float):
        self.frames, self.end, self.calls = frames, end, []

    def find(self, positions, radius_deg, collections=None, margin_px=0.0):
        self.calls.append((list(positions), radius_deg))
        return list(self.frames)

    def max_mjd(self, releases):
        return self.end


def test_day_path_spacing_follows_rate():
    slow = track.day_path(eph(61000.0, RA0, DEC0, rate=1.5))  # 0.01 deg/day
    fast = track.day_path(eph(61000.0, RA0, DEC0, rate=150.0))  # 1 deg/day
    assert len(slow) == 2 and len(fast) == 51
    step = np.hypot(np.diff([p[0] for p in fast]) * np.cos(np.radians(DEC0)),
                    np.diff([p[1] for p in fast]))
    assert step.max() <= track.INDEX_SPACING_DEG + 1e-9


def test_index_frames_keep_only_frames_of_that_day():
    idx = FakeIndex([frame(61000.2), frame(61002.0), frame(61000.4, det=2)], 62000.0)
    got = track.index_frames(idx, [eph(61000.0, RA0, DEC0)])
    assert [f.mjd for f in got] == [61000.2, 61000.4]
    assert idx.calls[0][1] == pytest.approx(track.INDEX_SPACING_DEG / 2 + track.INDEX_MARGIN_DEG)


def test_find_visits_uses_index_then_sia_after_its_end(monkeypatch):
    days = [eph(61000.0 + i, RA0, DEC0) for i in range(6)]
    idx = FakeIndex([frame(61001.1, key="a"), frame(61004.2, key="late")], end=61002.5)
    sia_days = []
    monkeypatch.setattr(track, "ephemeris_range", lambda c, a, b, s: days)
    monkeypatch.setattr(track, "ephemeris_at", lambda c, mjds: [eph(m, RA0, DEC0) for m in mjds])
    monkeypatch.setattr(track.localindex, "current", lambda: idx)
    monkeypatch.setenv(track.localindex.ENV_TAIL, "1")

    def fake_sia(queries, deadline=None):
        sia_days.extend(q.mjd_lo for q in queries)
        return [frame(61004.2, key="late")], 0
    monkeypatch.setattr(track, "frames_for", fake_sia)
    t = track.find_visits("136108;", 61006.0)
    assert t.n_index_days == 3  # days 61000-61002 end by 61002.5
    assert min(sia_days) == pytest.approx(61002.5)  # SIA starts where the index stops
    assert [v.frame.s3_key for v in t.visits] == ["a", "late"]  # index's 'late' not kept


def test_find_visits_without_index_is_sia_only(monkeypatch):
    monkeypatch.setattr(track, "ephemeris_range", lambda c, a, b, s: [eph(61000.0, RA0, DEC0)])
    monkeypatch.setattr(track, "ephemeris_at", lambda c, mjds: [eph(m, RA0, DEC0) for m in mjds])
    monkeypatch.setattr(track.localindex, "current", lambda: None)
    monkeypatch.setattr(track, "frames_for", lambda q, d=None: ([frame(61000.1)], 0))
    t = track.find_visits("136108;", 61001.0)
    assert t.n_index_days == 0 and t.n_cones == 1 and len(t.visits) == 1


def test_index_frames_with_a_real_index(tmp_path):
    """A real on-disk FrameIndex: the frame is found where the path crosses it, that day."""
    from spherex_index import build_index as bi

    from pxs.spherex.localindex import FrameIndex
    from spherex.index_helpers import fake_row

    bi.write_part(tmp_path, "dr1", "2025W17_4B", [fake_row(RA0, DEC0, mjd=60790.3)])
    bi.write_manifest(tmp_path, "test")
    idx = FrameIndex.load(tmp_path)
    on = track.index_frames(idx, [eph(60790.0, RA0, DEC0)])
    assert len(on) == 1 and on[0].mjd == pytest.approx(60790.3)
    assert track.index_frames(idx, [eph(60791.0, RA0, DEC0)]) == []  # other day
    assert track.index_frames(idx, [eph(60790.0, RA0, DEC0 + 4.0)]) == []  # off the frame


def test_days_after_index_end_are_flagged_without_sia_tail(monkeypatch):
    days = [eph(61000.0 + i, RA0, DEC0) for i in range(6)]
    monkeypatch.setattr(track, "ephemeris_range", lambda c, a, b, s: days)
    monkeypatch.setattr(track, "ephemeris_at", lambda c, mjds: [eph(m, RA0, DEC0) for m in mjds])
    monkeypatch.setattr(track.localindex, "current", lambda: FakeIndex([], end=61002.5))
    monkeypatch.delenv(track.localindex.ENV_TAIL, raising=False)
    monkeypatch.setattr(track, "frames_for", lambda q, d=None: pytest.fail("SIA must not be asked"))
    t = track.find_visits("136108;", 61006.0)
    assert t.n_cones == 0 and t.unsearched_after_mjd == 61002.5
