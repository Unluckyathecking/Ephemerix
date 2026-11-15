"""What the live service needs from the body pipeline: progress, a time budget that keeps
the passes already measured, controls from the frame index, and chunked parallel reads."""

from __future__ import annotations

import pytest

from pxs.solarsystem import controls, phot, pipeline
from pxs.solarsystem.controls import Control
from pxs.solarsystem.phot import BANDS, BandFlux
from pxs.solarsystem.track import Track, Visit

from .conftest import eph, frame
from .test_manifest_cli import BODY, DEC0, RA0, _read
from .test_track_stacks import FakeIndex


class Clock:
    """A clock that only moves when a pass reads its stamps."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def two_passes(monkeypatch) -> Clock:
    clock = Clock()
    first, second = _read(), _read()
    second = [(Visit(frame(v.frame.mjd + 200.0, key=f"late{i}"), v.eph), s)
              for i, (v, s) in enumerate(second)]

    def read(visits, half):
        clock.t += 100.0  # each pass takes 100 s
        return (first if visits[0].frame.mjd < 61100 else second), 0

    monkeypatch.setattr(pipeline, "read_visits", read)
    zero = tuple(BandFlux(b, 20, 0.001, 0.0005) for b in BANDS)
    monkeypatch.setattr(pipeline, "run_control", lambda v, h: Control(zero, (), 8, 40))
    visits = tuple(v for v, _ in first + second)
    monkeypatch.setattr(pipeline, "find_visits", lambda cmd, stop, **kw: Track(visits, (), 0, 0))
    return clock


def test_progress_names_each_pass(two_passes) -> None:
    seen: list[tuple[str, float]] = []
    run = pipeline.run_body(BODY, mjd_stop=61400.0, progress=lambda s, f: seen.append((s, f)),
                            clock=two_passes)
    assert len(run.passes) == 2
    stages = [s for s, _ in seen]
    assert any("pass 1 of 2" in s for s in stages) and any("pass 2 of 2" in s for s in stages)
    fractions = [f for _, f in seen]
    assert fractions == sorted(fractions) and fractions[-1] < 1.0


def test_budget_keeps_the_passes_done_and_warns(two_passes) -> None:
    run = pipeline.run_body(BODY, mjd_stop=61400.0, deadline=two_passes.t + 150.0,
                            clock=two_passes)
    assert len(run.passes) == 1
    assert any("Stopped after 1 of 2 SPHEREx passes" in w for w in run.warnings)
    assert run.stopped_early


def test_no_budget_left_measures_nothing(two_passes) -> None:
    run = pipeline.run_body(BODY, mjd_stop=61400.0, deadline=two_passes.t - 1.0,
                            clock=two_passes)
    assert run.passes == () and run.stopped_early


def test_sia_past_the_deadline_is_not_asked_and_counts_as_failed(monkeypatch) -> None:
    import time

    from pxs.solarsystem import track

    monkeypatch.setattr(track, "find_frames", lambda *a: pytest.fail("SIA asked"))
    q = track.Query(RA0, DEC0, 0.1, 61000.0, 61001.0)
    assert track.sia_frames(RA0, DEC0, 0.1, deadline=time.monotonic() - 1) is None
    assert track.frames_for([q, q], deadline=time.monotonic() - 1) == ([], 2)


def test_run_gives_the_sia_search_part_of_the_budget(monkeypatch) -> None:
    import time

    seen: dict = {}

    def find(cmd, stop, **kw):
        seen.update(kw)
        return Track((), (), 0, 0)

    monkeypatch.setattr(pipeline, "find_visits", find)
    pipeline.run_body(BODY, mjd_stop=61400.0, deadline=time.monotonic() + 100.0)
    left = seen["sia_deadline"] - time.monotonic()
    assert 0 < left <= pipeline.SEARCH_SHARE * 100.0
    seen.clear()
    pipeline.run_body(BODY, mjd_stop=61400.0)
    assert seen == {}  # no budget: the CLI searches as long as it takes


def test_controls_use_the_index_and_never_sia(monkeypatch) -> None:
    fs = [frame(m, det=d) for m in (60800.0, 61000.5, 61200.0) for d in (1, 2)]
    idx = FakeIndex(fs, end=62000.0)
    monkeypatch.setattr(controls, "usable_index", lambda: idx)
    monkeypatch.setattr(controls, "sia_frames", lambda *a, **k: pytest.fail("SIA asked"))
    got = controls.control_frames(eph(61000.0, RA0, DEC0), 61000.0, 61001.0, per_detector=2)
    assert sorted(f.mjd for f in got) == [60800.0, 60800.0, 61200.0, 61200.0]
    assert idx.calls == [([(RA0, DEC0)], controls.spx_config.POINT_RADIUS_DEG)]


def test_controls_fall_back_to_sia_without_an_index(monkeypatch) -> None:
    monkeypatch.setattr(controls, "usable_index", lambda: None)
    monkeypatch.setattr(controls, "sia_frames", lambda ra, dec: None)  # archive did not answer
    assert controls.frames_at(RA0, DEC0) == []


def test_reads_go_through_worker_chunks_when_processes_are_on(monkeypatch) -> None:
    read = _read(20)
    by_key = {v.frame.s3_key: s for v, s in read}
    chunks: list[int] = []

    def chunk(jobs, half):
        chunks.append(len(jobs))
        return [(f, by_key[f.s3_key]) for f, _, _ in jobs if f.s3_key != "k3"], 1

    monkeypatch.setattr(phot.procs, "workers", lambda: 4)
    monkeypatch.setattr(phot, "_read_chunk_io", chunk)
    got, failed = phot.read_visits([v for v, _ in read], half=5)
    assert sorted(chunks) == [4, 8, 8] and failed == 3
    assert [v.frame.s3_key for v, _ in got] == [f"k{i}" for i in range(20) if i != 3]
