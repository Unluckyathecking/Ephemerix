"""Binned errors: inflated by the measured empty-position or within-bin scatter, never shrunk."""

from dataclasses import dataclass, replace

import numpy as np
import pytest

from pxs.binning import corrected, detector_factors, make_bin
from pxs.spectra import combined_spectrum


@dataclass(frozen=True)
class P:
    wl_um: float
    bw_um: float
    flux_mjy: float | None
    err_mjy: float | None
    detector: int
    flagged: bool
    mjd: float
    reason: str = ""
    empty_mjy: tuple[float, ...] = ()


def _passes(n_pass: int, n_wl: int, err: float, frame_sigma: float, shared_sigma: float,
            seed: int) -> list[list[P]]:
    """n_pass passes of n_wl points. Empty positions get independent noise `frame_sigma`
    per frame plus `shared_sigma` that is the same in every frame (fixed sky structure)."""
    rng = np.random.default_rng(seed)
    shared = rng.normal(0, shared_sigma, (n_wl, 8))
    out = []
    for k in range(n_pass):
        pts = []
        for i in range(n_wl):
            wl = 1.0 + 0.025 * i
            empty = tuple(float(v) for v in rng.normal(0, frame_sigma, 8) + shared[i])
            pts.append(P(wl, wl / 40, 1.0 + rng.normal(0, frame_sigma), err, 1, False,
                         60700.0 + 200 * k, empty_mjy=empty))
        out.append(pts)
    return out


def _bins(passes):
    allp = [p for ps in passes for p in ps]
    return [make_bin([p for p in allp if abs(p.wl_um - wl) < 1e-9], wl - 0.01, wl + 0.01)
            for wl in sorted({p.wl_um for p in allp})]


def test_independent_noise_leaves_errors_alone() -> None:
    empty, scatter = detector_factors(_bins(_passes(4, 60, 0.1, 0.1, 0.0, seed=1)))[1]
    assert empty == pytest.approx(1.0, abs=0.15)
    assert scatter == pytest.approx(1.0, abs=0.15)


def test_noise_shared_across_frames_is_measured_from_empty_positions() -> None:
    # Per frame sigma 0.1 is honest, but 0.1 shared by all 4 frames makes a 4-frame mean
    # sqrt(0.1^2/4 + 0.1^2) = 0.112 uncertain, not 0.05: factor about 2.2.
    empty, _ = detector_factors(_bins(_passes(4, 60, 0.1, 0.1, 0.1, seed=2)))[1]
    assert empty == pytest.approx(np.sqrt(0.01 / 4 + 0.01) / 0.05, rel=0.2)


def test_scatter_beyond_the_errors_inflates_them() -> None:
    # Points scatter by 0.3 but claim 0.1: factor about 3.
    _, scatter = detector_factors(_bins(_passes(4, 60, 0.1, 0.3, 0.0, seed=3)))[1]
    assert scatter == pytest.approx(3.0, rel=0.2)


def test_a_bin_with_enough_frames_uses_its_own_scatter() -> None:
    # Six frames claiming 0.1 but spread by about 1: the bin error is their standard error.
    pts = [P(2.0, 0.05, f, 0.1, 1, False, 60700.0 + k)
           for k, f in enumerate([0.0, 2.0, 1.0, -1.0, 3.0, 1.0])]
    (b,) = corrected([make_bin(pts, 1.99, 2.01)])
    assert b.err == pytest.approx(np.std([0.0, 2.0, 1.0, -1.0, 3.0, 1.0], ddof=1) / np.sqrt(6))


def test_a_bin_that_happens_to_agree_keeps_the_pooled_scatter_factor() -> None:
    # Many 4-frame bins scatter 3x their errors; a bin whose frames happen to agree
    # (here 2 and 4 identical frames) still gets the pooled factor.
    passes = _passes(4, 60, 0.1, 0.3, 0.0, seed=6)
    bins = _bins(passes)
    pair = make_bin([P(9.0, 0.2, 1.0, 0.1, 1, False, 1.0), P(9.0, 0.2, 1.0, 0.1, 1, False, 2.0)],
                    8.9, 9.1)
    four = make_bin([P(9.5, 0.2, 1.0, 0.1, 1, False, float(k)) for k in range(4)], 9.4, 9.6)
    out = corrected([*bins, pair, four])
    assert out[-2].err == pytest.approx(pair.err * 3.0, rel=0.2)
    assert out[-1].err == pytest.approx(four.err * 3.0, rel=0.2)


def test_empty_positions_set_a_floor_even_without_scatter() -> None:
    # Frames agree exactly (no scatter), but the empty positions vary together by 0.1.
    passes = _passes(4, 60, 0.1, 0.0001, 0.1, seed=7)
    bins = _bins(passes)
    out = corrected(bins)
    assert np.median([o.err / b.err for o, b in zip(out, bins)]) > 1.8


def test_errors_are_never_shrunk_and_inputs_untouched() -> None:
    bins = _bins(_passes(4, 30, 1.0, 0.01, 0.0, seed=4))  # claimed errors far too big
    out = corrected(bins)
    assert [b.err for b in out] == [b.err for b in bins]
    assert out is not bins


def test_combined_spectrum_uses_the_corrected_errors() -> None:
    passes = _passes(4, 60, 0.1, 0.1, 0.1, seed=5)
    plain = [[replace(p, empty_mjy=()) for p in ps] for ps in passes]
    errs = [p["err"] for p in combined_spectrum(passes)["points"]]
    nominal = [p["err"] for p in combined_spectrum(plain)["points"]]
    assert np.median(np.array(errs) / np.array(nominal)) > 1.8


def test_points_without_empty_fluxes_still_bin() -> None:
    pts = [[P(1.0 + 0.025 * i, 0.025, 1.0, 0.1, 2, False, 60700.0) for i in range(20)]] * 3
    spec = combined_spectrum(pts)
    # 3 or 6 identical points per bin (some bins span two wavelengths), no inflation.
    assert {p["err"] for p in spec["points"]} == {round(0.1 / np.sqrt(3), 6),
                                                  round(0.1 / np.sqrt(6), 6)}
