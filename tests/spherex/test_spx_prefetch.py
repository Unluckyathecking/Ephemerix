"""prefetch_pass reads each frame once, and afterwards stack_pass and extract_spectrum find
every stamp they ask for in the cache (no further reads)."""

from dataclasses import replace

import numpy as np
import pytest

from pxs.grid import Grid
from pxs.spherex import Frame, Pass, Target, prefetch, stamps
from pxs.spherex.prefetch import prefetch_pass, requests_for
from pxs.spherex.read import Request
from pxs.spherex.spectrum import extract_spectrum
from pxs.spherex.stack import stack_pass

from .conftest import synthetic_stamp

RA, DEC = 150.0, 2.0
GRID = Grid(RA, DEC, fov_arcsec=120.0, size_px=60)
TARGET = Target(name="t", ra=RA, dec=DEC, epoch=2025.5, pmra_masyr=500.0, pmdec_masyr=-300.0)


def _pass(n: int = 6) -> Pass:
    return Pass(tuple(Frame("spherex_dr1", f"o{i}", 6, 61000.0 + 0.1 * i, f"key{i}", 4.4, 5.0)
                      for i in range(n)))


def _fake_reader(calls: list, psf: np.ndarray):
    def read(store, key: str, reqs: list[Request], prefetch: bool = True):
        calls.append((key, len(reqs)))
        out = []
        for r in reqs:
            n = 2 * r.half + 1
            s = synthetic_stamp(np.zeros((n, n)), ra=r.ra, dec=r.dec, psf=psf if r.with_psf else None)
            out.append(replace(s, key=key))
        return out
    return read


def test_one_read_per_frame_then_no_reads(monkeypatch: pytest.MonkeyPatch,
                                          gaussian_psf: np.ndarray) -> None:
    calls: list = []
    monkeypatch.setattr(prefetch, "read_stamps", _fake_reader(calls, gaussian_psf))

    def no_read(*args, **kwargs):
        raise AssertionError("a stamp was read again after the prefetch")

    monkeypatch.setattr(stamps, "_read_uncached", no_read)
    pas = _pass()
    ticks: list[tuple[int, int]] = []
    got = prefetch_pass(pas, GRID, TARGET, on_frame=lambda d, t: ticks.append((d, t)))
    assert got.n_frames == 6 and got.n_failed == 0
    assert sorted(calls) == [(f.s3_key, 2) for f in pas.frames]  # both stamps, one open
    assert sorted(ticks) == [(i, 6) for i in range(1, 7)]
    assert stack_pass(pas, GRID, (4.4, 5.0), TARGET) is not None
    assert len(extract_spectrum(pas, TARGET)) == 6
    prefetch_pass(pas, GRID, TARGET)  # everything cached: nothing is read again
    assert len(calls) == 6


def test_requests_match_what_the_stack_and_spectrum_ask_for() -> None:
    f = _pass(1).frames[0]
    stack_req, spec_req = requests_for(f, GRID, TARGET)
    assert (stack_req.ra, stack_req.dec, stack_req.with_psf) == (RA, DEC, False)
    assert (spec_req.ra, spec_req.dec) == stamps.position_at(TARGET, f.mjd)
    assert spec_req.with_psf and spec_req.half == 15
    assert [r.with_psf for r in requests_for(f, GRID, None)] == [False]


def test_a_failing_frame_is_left_for_the_normal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(store, key, reqs, prefetch=True):
        raise OSError("reset")

    monkeypatch.setattr(prefetch, "read_stamps", broken)
    assert prefetch_pass(_pass(3), GRID, TARGET).n_failed == 3


def test_a_cancellation_in_the_callback_stops_the_prefetch(monkeypatch: pytest.MonkeyPatch,
                                                           gaussian_psf: np.ndarray) -> None:
    class Stop(BaseException):
        pass

    monkeypatch.setattr(prefetch, "read_stamps", _fake_reader([], gaussian_psf))

    def cancel(done: int, total: int) -> None:
        raise Stop

    with pytest.raises(Stop):
        prefetch_pass(_pass(), GRID, TARGET, on_frame=cancel)
