"""Warmup: indexed passes are stacked and measured ahead; identical calls reuse the result."""

from pxs.api.progress import SpherexProgress
from pxs.api.warmup import MISS, Warmup, spectrum_key, stack_key
from pxs.grid import Grid
from pxs.sources import SPHEREX_WINDOWS

GRID = Grid(1.0, 2.0, 240.0, 240)


class _Inner:
    def __init__(self, passes, fail_spectrum=False) -> None:
        self.passes, self.fail_spectrum = passes, fail_spectrum
        self.calls: list[tuple] = []

    def warm_from_index(self, target, grid, on_frame):
        return self.passes

    def stack_pass(self, pas, grid, window, target):
        self.calls.append(("stack", pas, window))
        return f"stack {pas} {window}"

    def extract_spectrum(self, pas, target, neighbours=None):
        self.calls.append(("spectrum", pas, neighbours))
        if self.fail_spectrum:
            raise RuntimeError("fit failed")
        return f"spectrum {pas} {neighbours}"


def test_warm_results_are_served_for_identical_calls_only() -> None:
    target = object()
    inner = _Inner(["p1", "p2"])
    w = Warmup(inner)
    w.start(GRID, target, lambda pas: [(1.0, 2.0)]).result(5)
    window = next(iter(SPHEREX_WINDOWS.values()))
    assert w.get(stack_key("p1", GRID, window, target)) == f"stack p1 {window}"
    assert w.get(spectrum_key("p2", target, [(1.0, 2.0)])) == "spectrum p2 [(1.0, 2.0)]"
    assert w.get(spectrum_key("p2", target, None)) is MISS  # other neighbours: not the same call
    assert w.get(stack_key("p3", GRID, window, target)) is MISS  # a pass IRSA's frames changed
    assert len(inner.calls) == 2 * (len(SPHEREX_WINDOWS) + 1)


def test_a_failed_warm_call_is_computed_again_by_the_build() -> None:
    target = object()
    inner = _Inner(["p1"], fail_spectrum=True)
    spx = SpherexProgress(inner, lambda s, f: None, (0.0, 1.0))
    spx.warm(GRID, target, None)
    spx._warmup.job.result(5)  # the warm attempt has failed by now
    try:
        spx.extract_spectrum("p1", target)
    except RuntimeError:
        pass
    assert [c for c in inner.calls if c[0] == "spectrum"] == [("spectrum", "p1", None)] * 2


def test_the_build_reuses_a_warm_stack_without_calling_the_module() -> None:
    target = object()
    inner = _Inner(["p1"])
    spx = SpherexProgress(inner, lambda s, f: None, (0.0, 1.0))
    spx.warm(GRID, target, None)
    window = next(iter(SPHEREX_WINDOWS.values()))
    spx._warmup.wait_reads()
    out = spx.stack_pass("p1", GRID, window, target)  # waits for the warm result if needed
    assert out == f"stack p1 {window}"
    assert sum(c[0] == "stack" and c[2] == window for c in inner.calls) == 1
