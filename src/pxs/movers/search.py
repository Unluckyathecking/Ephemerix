"""Shift-and-stack of matched-filter planes along trial trajectories (numpy, CPU).

Each trial is a set of integer pixel offsets, one per frame (rounded from the trajectory
model; trials that round to the same offsets are searched once). For a trial, the S/N map
over start (mid-pass) positions is sum_i psi_i(x + o_i) / sqrt(sum_i phi_i(x + o_i)).
The running maximum over trials and the index of the trial that reached it are kept.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .geometry import PassGeometry, TrajectoryGrid
from .matched import Planes

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.3  # sum(phi) along a track must reach this share of the field's median
MIN_MOTION_PX = 1.5  # tracks must reach this far from mid-pass (3 px end to end)


@dataclass(frozen=True)
class Trials:
    """Unique integer offset sets. offsets: (m, 2, n) int; rep: (m,) index of one trajectory
    in the TrajectoryGrid that produced each set."""

    offsets: np.ndarray
    rep: np.ndarray

    def __len__(self) -> int:
        return int(self.offsets.shape[0])


def track_span_px(off: np.ndarray) -> np.ndarray:
    """Largest distance (px) between any track position and the mid-pass one, per trial."""
    return np.max(np.hypot(off[:, 0], off[:, 1]), axis=1) if off.size else np.zeros(0)


def make_trials(geom: PassGeometry, grid: TrajectoryGrid,
                min_motion_px: float = MIN_MOTION_PX) -> Trials:
    """Integer offsets of every trajectory that moves at least min_motion_px from its
    mid-pass position, deduplicated. Slower tracks are degenerate with static-source
    residuals, which differencing between passes leaves at the 10-50% level on bright stars."""
    v = np.stack([grid.vx, grid.vy], axis=1)  # (m, 2)
    off = v[:, :, None] * geom.dt[None, None, :] + geom.curve_px[None] / grid.d_au[:, None, None]
    ints = np.rint(off).astype(np.int32)
    moving = np.flatnonzero(track_span_px(off) >= min_motion_px)
    flat = ints[moving].reshape(moving.size, -1)
    _, first = np.unique(flat, axis=0, return_index=True)
    keep = moving[np.sort(first)]
    return Trials(ints[keep], keep)


@dataclass(frozen=True)
class SearchMaps:
    """best_snr, best_trial (index into Trials), best_flux_mjy, coverage (sum phi of the best
    trial over the field median) per start pixel; n_trials searched; seconds taken."""

    best_snr: np.ndarray
    best_trial: np.ndarray
    coverage: np.ndarray
    n_trials: int
    seconds: float


def _shifted_sum(arr: np.ndarray, off: np.ndarray, pad: int) -> np.ndarray:
    """sum_i arr_i(y + oy_i, x + ox_i) for padded arr (n, H+2p, W+2p) -> (H, W)."""
    n, hp, wp = arr.shape
    h, w = hp - 2 * pad, wp - 2 * pad
    acc = np.zeros((h, w), np.float32)
    for i in range(n):
        ox, oy = int(off[0, i]), int(off[1, i])
        acc += arr[i, pad + oy:pad + oy + h, pad + ox:pad + ox + w]
    return acc


def track_sums(pl: Planes, off: np.ndarray, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame psi and phi along one track starting at pixel (x, y); 0 off the field."""
    n, h, w = pl.psi.shape
    xs, ys = x + off[0], y + off[1]
    inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    idx = np.arange(n)
    psi = np.zeros(n, np.float32)
    phi = np.zeros(n, np.float32)
    psi[inside] = pl.psi[idx[inside], ys[inside], xs[inside]]
    phi[inside] = pl.phi[idx[inside], ys[inside], xs[inside]]
    return psi, phi


def run_search(pl: Planes, trials: Trials, mirror: bool = False) -> SearchMaps:
    """Max S/N over all trials at each start pixel. mirror=True negates every offset (the
    null search: same trial count, but no real mover stacks coherently)."""
    t = time.time()
    sign = -1 if mirror else 1
    pad = int(np.abs(trials.offsets).max()) + 1 if len(trials) else 1
    psi = np.pad(pl.psi, ((0, 0), (pad, pad), (pad, pad)))
    phi = np.pad(pl.phi, ((0, 0), (pad, pad), (pad, pad)))
    h, w = pl.psi.shape[1:]
    full = np.median(pl.phi.sum(axis=0)[pl.phi.sum(axis=0) > 0]) if np.any(pl.phi) else 1.0
    best = np.full((h, w), -np.inf, np.float32)
    idx = np.full((h, w), -1, np.int32)
    cov = np.zeros((h, w), np.float32)
    for j in range(len(trials)):
        off = sign * trials.offsets[j]
        sp, sf = _shifted_sum(psi, off, pad), _shifted_sum(phi, off, pad)
        ok = sf >= MIN_COVERAGE * full
        with np.errstate(invalid="ignore", divide="ignore"):
            snr = np.where(ok, sp / np.sqrt(np.where(ok, sf, 1.0)), -np.inf)
        better = snr > best
        best = np.where(better, snr, best)
        idx = np.where(better, j, idx)
        cov = np.where(better, sf / full, cov)
    secs = time.time() - t
    log.info("searched %d trials over %dx%d px in %.1f s", len(trials), w, h, secs)
    return SearchMaps(best, idx, cov, len(trials), secs)
