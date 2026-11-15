"""Progress: step counts stay within their totals, and the bar only moves forward while WISE
and SPHEREx (several passes and frames at once) report together."""

import threading
from dataclasses import dataclass

from build_fakes import GRID, MOVER, FakeSpherex, FakeWise

from pxs.api.progress import SPHEREX_SPAN, Combined, SpherexProgress, Tracker, WiseProgress
from pxs.sources import collect_spherex, collect_wise


def _counts(stage: str) -> tuple[int, int]:
    inner = stage[stage.index("(") + 1:stage.index(")")]
    done, total = (int(v) for v in inner.split(" of "))
    return done, total


def test_steps_never_exceed_the_total_and_end_at_the_span() -> None:
    # With six SPHEREx windows the proxy used to assume four steps per pass and reported
    # "Reading SPHEREx images (13 of 12)" on a real build.
    seen: list[tuple[str, float]] = []
    lock = threading.Lock()

    def report(s: str, f: float) -> None:
        with lock:
            seen.append((s, f))

    collect_spherex(SpherexProgress(FakeSpherex(MOVER), report), MOVER, GRID)
    steps = [_counts(s) for s, _ in seen if "(" in s]
    assert all(d <= t for d, t in steps)
    assert max(d for d, _ in steps) == steps[0][1] == len(steps)  # passes run at once
    assert max(f for _, f in seen) <= SPHEREX_SPAN[1]


@dataclass(frozen=True)
class _Pass:
    frames: tuple[float, ...]


class _Prefetching(FakeSpherex):
    """FakeSpherex whose passes have frames and which can prefetch them on threads."""

    def group_passes(self, frames):
        return [_Pass((60700.0, 60701.0, 60702.0)), _Pass((60880.0, 60881.0))]

    def stack_pass(self, pas, grid, window_um, target=None):
        return super().stack_pass(list(pas.frames), grid, window_um, target)

    def extract_spectrum(self, pas, target):
        return super().extract_spectrum(list(pas.frames), target)

    def prefetch_pass(self, pas, grid, target=None, on_frame=None):
        threads = [threading.Thread(target=on_frame, args=(i + 1, len(pas.frames)))
                   for i in range(len(pas.frames))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def test_both_sources_at_once_give_one_monotonic_bar_naming_both() -> None:
    tracker = Tracker()
    seen: list[tuple[str, float]] = []
    lock = threading.Lock()

    def report(s: str, f: float) -> None:
        tracker.report(s, f)
        with lock:
            seen.append((s, tracker.snapshot()[1]))

    both = Combined(report)
    spx = SpherexProgress(_Prefetching(MOVER), both.part("spherex"), (0.0, 1.0))
    wise = WiseProgress(FakeWise(MOVER), both.part("wise"), (0.0, 1.0))
    jobs = [threading.Thread(target=collect_spherex, args=(spx, MOVER, GRID)),
            threading.Thread(target=collect_wise, args=(wise, MOVER, GRID))]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join(30)
    fractions = [f for _, f in seen]
    assert fractions == sorted(fractions)  # the job's bar never moves back
    assert fractions[-1] <= 0.8 + 1e-9 and fractions[-1] > 0.79  # both parts finished
    assert any("Reading SPHEREx images (5 of 5)" in s for s, _ in seen)


def test_combined_names_every_part_in_flight_and_never_goes_back() -> None:
    out: list[tuple[str, float]] = []
    both = Combined(lambda s, f: out.append((s, f)), span=(0.0, 1.0),
                    weights={"wise": 1.0, "spherex": 1.0})
    w, s = both.part("wise"), both.part("spherex")
    w("Reading WISE images (1 of 4)", 0.25)
    s("Reading SPHEREx images (10 of 100)", 0.1)
    assert out[-1] == ("Reading WISE images (1 of 4); reading SPHEREx images (10 of 100)",
                       0.175)
    w("Reading WISE images (0 of 8)", 0.0)  # a part's total grew: its share does not drop
    assert out[-1][1] == 0.175
    w("WISE images read", 1.0)
    assert out[-1][0] == "Reading SPHEREx images (10 of 100)"
