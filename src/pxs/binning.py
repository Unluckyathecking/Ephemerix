"""Honest errors for wavelength bins that average many SPHEREx frames.

Units: micrometres, mJy. A bin's propagated error, 1 / sqrt(sum w) with w = 1 / err^2,
assumes the frames are independent and their errors right. Neither holds:
- bright sources scatter between frames by 2-8 times their errors (PSF model, pixel phase,
  flat field; measured on Eps Ind B, DENIS 0255, 2MASS 0559 at 1-3% of the flux);
- at one sky position the background and confusion structure repeat in every frame, so
  averaging N frames gains less than sqrt(N) (WISE 0855 at 4.4-5.0 um over four passes:
  S/N 30 from the errors, 20 from the empty positions; UGPS 0722: 88 against 32).

The rule, per bin:

    err = max(propagated x pooled scatter factor, own scatter, propagated x empty factor)

- pooled scatter factor: sqrt(sum chi2 / sum dof) of the frames about their bin means,
  over all bins of the detector. Measured on the six brown dwarfs: 1.0-1.3 for faint
  ones, 2-8 for bright ones (systematics of 1-3% of the flux).
- own scatter: the bin's standard error of the mean,
  sqrt(sum w (f - mean)^2 / (n - 1) / sum w), when it has n >= MIN_SCATTER_POINTS usable
  frames. It raises bins that scatter more than their detector does (a pass hit by a
  cosmic ray or a neighbour). It is never used to lower an error: from 3-4 frames it is
  too noisy for that (with 2 degrees of freedom it falls below half the true value about
  one time in five; used alone it raised the floor-free chi2 of the bright targets 1.2-3.8
  times).
- empty factor: the robust spread of the same inverse-variance mean taken at the 8 empty
  positions next to the target (SpecPoint.empty_mjy, fixed on the sky), in units of the
  propagated error, pooled over the detector's bins. It catches noise that is
  correlated across frames, but not the target's own photon noise.

A detector with too few samples for a pooled factor takes the value pooled over all
detectors. Errors are never shrunk below the propagated error.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

MIN_EMPTY = 16  # binned empty fluxes needed to trust a detector's empty factor
MIN_DOF = 5  # within-bin degrees of freedom needed to trust a detector's scatter factor
MIN_SCATTER_POINTS = 3  # usable frames for a bin's own standard error (2 dof)


@dataclass(frozen=True)
class Bin:
    """One wavelength bin before the error correction. `flux`, `err` None when flagged."""

    wl_um: float
    bw_um: float
    flux: float | None
    err: float | None
    detector: int | None
    chi2: float = 0.0
    dof: int = 0
    empty_z: tuple[float, ...] = ()  # binned empty fluxes in units of the nominal error

    @property
    def scatter_err(self) -> float | None:
        """Standard error of the mean from the bin's own scatter, when it has enough frames."""
        if self.err is None or self.dof + 1 < MIN_SCATTER_POINTS:
            return None
        return self.err * math.sqrt(self.chi2 / self.dof)


def _num(v) -> float | None:
    return float(v) if v is not None and math.isfinite(float(v)) else None


def usable(p) -> bool:
    f, e = _num(p.flux_mjy), _num(p.err_mjy)
    return not p.flagged and f is not None and e is not None and e > 0


def _empty_z(good, w: np.ndarray, sigma: float) -> tuple[float, ...]:
    rows = [getattr(p, "empty_mjy", ()) or () for p in good]
    if not rows or any(len(r) != len(rows[0]) for r in rows) or not rows[0]:
        return ()
    e = np.array(rows, dtype=float)
    out = []
    for k in range(e.shape[1]):
        ok = np.isfinite(e[:, k])
        if ok.any():
            out.append(float((w[ok] * e[ok, k]).sum() / w[ok].sum() / sigma))
    return tuple(out)


def make_bin(points: Sequence, lo: float, hi: float) -> Bin:
    """Inverse-variance mean of the usable points in [lo, hi); flagged when there are none."""
    good = [p for p in points if usable(p)]
    detector = Counter(p.detector for p in points).most_common(1)[0][0] if points else None
    if not good:
        return Bin(0.5 * (lo + hi), hi - lo, None, None, detector)
    w = np.array([1.0 / float(p.err_mjy) ** 2 for p in good])
    f = np.array([float(p.flux_mjy) for p in good])
    wl = np.array([p.wl_um for p in good])
    mean, sigma = float((w * f).sum() / w.sum()), 1.0 / math.sqrt(w.sum())
    chi2 = float((w * (f - mean) ** 2).sum())
    return Bin(float((w * wl).sum() / w.sum()), hi - lo, mean, sigma, detector, chi2,
               len(good) - 1, _empty_z(good, w, sigma))


def _robust_sigma(z: Sequence[float]) -> float:
    a = np.asarray(z, float)
    return 1.4826 * float(np.median(np.abs(a - np.median(a))))


def _factor(bins: Sequence[Bin]) -> tuple[float | None, float | None]:
    """(empty factor, scatter factor) of a set of bins, None where samples are too few."""
    z = [v for b in bins for v in b.empty_z]
    dof = sum(b.dof for b in bins)
    empty = _robust_sigma(z) if len(z) >= MIN_EMPTY else None
    scatter = math.sqrt(sum(b.chi2 for b in bins) / dof) if dof >= MIN_DOF else None
    return empty, scatter


def detector_factors(bins: Sequence[Bin]) -> dict[int | None, tuple[float, float]]:
    """(empty factor, pooled scatter factor) per detector, each >= 1."""
    measured = [b for b in bins if b.flux is not None]
    overall = _factor(measured)
    out = {}
    for det in sorted({b.detector for b in measured}, key=lambda d: -1 if d is None else d):
        own = _factor([b for b in measured if b.detector == det])
        parts = [o if o is not None else a for o, a in zip(own, overall)]
        out[det] = tuple(max(1.0, p) if p is not None else 1.0 for p in parts)
    return out


def honest_err(b: Bin, empty_factor: float, scatter_factor: float) -> float | None:
    """The bin's error by the rule in the module docstring (factors are >= 1)."""
    if b.err is None:
        return None
    own = b.scatter_err or 0.0
    return max(b.err * scatter_factor, own, b.err * empty_factor)


def corrected(bins: Sequence[Bin]) -> list[Bin]:
    """The bins with honest errors (new objects; inputs are not modified)."""
    factors = detector_factors(bins)
    return [b if b.err is None else Bin(b.wl_um, b.bw_um, b.flux,
                                        honest_err(b, *factors[b.detector]), b.detector,
                                        b.chi2, b.dof, b.empty_z) for b in bins]
