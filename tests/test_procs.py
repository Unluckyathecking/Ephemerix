"""Worker-process offloading: off by default, results and errors come back when on."""

import math
import os

import pytest

from pxs import procs


def test_off_by_default_runs_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(procs.ENV, raising=False)
    seen = []
    f = procs.offloaded(lambda x: seen.append(os.getpid()) or x * 2)  # a lambda cannot pickle
    assert f(21) == 42 and seen == [os.getpid()]


@pytest.mark.parametrize("value, n", [("3", 3), ("0", 0), ("", 0), ("lots", 0), ("-2", 0)])
def test_worker_count_from_the_environment(monkeypatch: pytest.MonkeyPatch, value: str,
                                           n: int) -> None:
    monkeypatch.setenv(procs.ENV, value)
    assert procs.workers() == n


def test_results_and_errors_cross_the_process_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(procs.ENV, "2")
    monkeypatch.setattr(procs, "PRELOAD", [])  # keep the test's fork server light
    try:
        assert procs.offloaded(math.hypot)(3.0, 4.0) == 5.0
        with pytest.raises(ValueError):
            procs.offloaded(math.sqrt)(-1.0)
        assert procs.offloaded(os.getpid)() != os.getpid()
    finally:
        procs.shutdown()
