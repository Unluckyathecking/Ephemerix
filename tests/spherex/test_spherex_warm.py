"""The index warm-up reads the indexed frames' stamps while the IRSA tail search runs."""

import threading

from pxs.grid import Grid
from pxs.spherex import localindex, prefetch
from pxs.spherex.types import Frame


def _frame(i: int, mjd: float) -> Frame:
    return Frame(collection="spherex_qr3", obs_id=f"o{i}", detector=1, mjd=mjd,
                 s3_key=f"k{i}", em_min_um=1.0, em_max_um=1.1)


class _Target:
    ra, dec, has_pm = 10.0, -5.0, False


def test_warm_prefetches_every_indexed_pass_and_counts_frames(monkeypatch) -> None:
    frames = [_frame(0, 60000.0), _frame(1, 60001.0), _frame(2, 60100.0)]
    monkeypatch.setattr(localindex, "try_lookup",
                        lambda *a, **k: localindex.LocalResult(frames, sia_after_mjd=60200.0))
    seen, lock = [], threading.Lock()

    def fake_prefetch(pas, grid, target, on_frame=None):
        with lock:
            seen.append(tuple(f.obs_id for f in pas.frames))
        on_frame(len(pas.frames), len(pas.frames))

    monkeypatch.setattr(prefetch, "prefetch_pass", fake_prefetch)
    ticks = []
    n = prefetch.warm_from_index(_Target(), Grid(10.0, -5.0, 240.0, 240),
                                 lambda d, t: ticks.append((d, t)))
    assert [len(p.frames) for p in n] == [2, 1]
    assert sorted(seen) == [("o0", "o1"), ("o2",)]  # passes split as group_passes does
    assert max(ticks) == (3, 3)


def test_warm_does_nothing_without_an_irsa_tail_to_overlap(monkeypatch) -> None:
    monkeypatch.setattr(localindex, "try_lookup",
                        lambda *a, **k: localindex.LocalResult([_frame(0, 60000.0)], None))
    monkeypatch.setattr(prefetch, "prefetch_pass", lambda *a, **k: 1 / 0)
    assert prefetch.warm_from_index(_Target(), Grid(10.0, -5.0, 240.0, 240)) == []
