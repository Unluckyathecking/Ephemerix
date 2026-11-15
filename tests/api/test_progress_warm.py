"""SpherexProgress: the warm-up runs during the search and the pass reads wait for it."""

import threading

import pytest

from pxs.api.progress import SpherexProgress, WiseProgress
from pxs.grid import Grid


class _Inner:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.order: list[str] = []

    def warm_from_index(self, target, grid, on_frame):
        on_frame(1, 2)
        self.release.wait(5)
        self.order.append("warm")
        return []  # no passes to stack ahead

    def prefetch_pass(self, pas, grid, target, on_frame=None):
        self.order.append("prefetch")


def test_prefetch_waits_for_the_warm_up_and_progress_names_the_reads() -> None:
    inner, reports = _Inner(), []
    spx = SpherexProgress(inner, lambda s, f: reports.append(s), (0.0, 1.0))
    spx.warm(Grid(1.0, 2.0, 240.0, 240), object())
    t = threading.Thread(target=spx.prefetch_pass, args=(object(), None, None))
    t.start()
    t.join(0.2)
    assert t.is_alive()  # still waiting for the warm-up
    inner.release.set()
    t.join(5)
    assert inner.order == ["warm", "prefetch"]
    assert "Reading SPHEREx images (1 of 2)" in reports


def test_a_failed_wise_search_is_no_longer_shown_as_running() -> None:
    class Down:
        def find_visits(self, ra, dec, **kw):
            raise RuntimeError("IRSA down")

    reports = []
    w = WiseProgress(Down(), lambda s, f: reports.append((s, f)), (0.0, 1.0))
    with pytest.raises(RuntimeError):
        w.find_visits(1.0, 2.0)
    assert reports[-1] == ("WISE search failed", 1.0)
