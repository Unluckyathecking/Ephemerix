"""Peaks of the search maps -> candidates: track-level outlier clipping, duplicates merged.

A peak's S/N is recomputed along its own track with per-frame clipping (a frame whose flux
is more than CLIP_NSIG sigma from the track's fitted flux is dropped, repeatedly), which
removes cosmic rays, persistence and single-frame asteroids that otherwise lift a track.
Peaks whose tracks run within MERGE_PX of a stronger candidate's track in at least
MERGE_SHARE of frames are the same object seen through a neighbouring trial and merged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import maximum_filter

from .matched import Planes, flux_mjy
from .search import SearchMaps, Trials, track_sums

PEAK_BOX = 5
MAX_PEAKS = 400
CLIP_NSIG = 4.0
MERGE_PX = 2.5
MERGE_SHARE = 0.3
SHADOW_PX = 3.0
SHADOW_KEEP = 0.6


@dataclass(frozen=True)
class Detection:
    """One candidate track. x, y: grid px (pixel index) at mid-pass. trial: index into Trials.
    snr_raw: S/N of the plain stack; snr: after clipping. flux_mjy: at the template's
    reference wavelength. n_frames / n_clipped: frames on the track / dropped by clipping.
    snr_first, snr_second: S/N of each half of the pass. max_frame_share: largest single
    frame's share of the clipped S/N."""

    x: int
    y: int
    trial: int
    snr_raw: float
    snr: float
    flux_mjy: float
    flux_err_mjy: float
    n_frames: int
    n_clipped: int
    snr_first: float
    snr_second: float
    max_frame_share: float


def peaks(maps: SearchMaps, threshold: float) -> list[tuple[int, int]]:
    """(x, y) of local maxima of the best-S/N map above threshold, strongest first."""
    snr = np.where(np.isfinite(maps.best_snr), maps.best_snr, -np.inf)
    is_max = (snr == maximum_filter(snr, size=PEAK_BOX, mode="nearest")) & (snr >= threshold)
    ys, xs = np.nonzero(is_max)
    order = np.argsort(snr[ys, xs])[::-1][:MAX_PEAKS]
    return [(int(xs[i]), int(ys[i])) for i in order]


def _snr(psi: np.ndarray, phi: np.ndarray) -> float:
    s = float(phi.sum())
    return float(psi.sum()) / np.sqrt(s) if s > 0 else 0.0


def measure_track(pl: Planes, off: np.ndarray, x: int, y: int, dt: np.ndarray,
                  trial: int, exclude: np.ndarray | None = None) -> Detection:
    """Clipped S/N, flux and consistency numbers of one track; `exclude` drops frames."""
    psi, phi = track_sums(pl, off, x, y)
    if exclude is not None:
        psi, phi = np.where(exclude, 0, psi), np.where(exclude, 0, phi)
    use = phi > 0
    for _ in range(5):
        if not use.any():
            break
        f = psi[use].sum() / phi[use].sum()
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(phi > 0, (psi / np.where(phi > 0, phi, 1) - f) * np.sqrt(phi), 0)
        new = (phi > 0) & (np.abs(z) <= CLIP_NSIG)
        if np.array_equal(new, use):
            break
        use = new
    p, q = np.where(use, psi, 0), np.where(use, phi, 0)
    snr = _snr(p, q)
    share = float(np.max(p / np.sqrt(q.sum()))) / snr if snr > 0 and q.sum() > 0 else 1.0
    first, second = dt < 0, dt >= 0
    tot_phi = float(q.sum())
    return Detection(
        x=x, y=y, trial=trial, snr_raw=_snr(psi, phi), snr=snr,
        flux_mjy=float(flux_mjy(np.array(p.sum()), np.array(tot_phi))),
        flux_err_mjy=float(flux_mjy(np.array(np.sqrt(tot_phi)), np.array(tot_phi)))
        if tot_phi > 0 else float("nan"),
        n_frames=int((phi > 0).sum()), n_clipped=int(((phi > 0) & ~use).sum()),
        snr_first=_snr(p[first], q[first]), snr_second=_snr(p[second], q[second]),
        max_frame_share=share)


def track_xy(trials: Trials, d: Detection, sign: int = 1) -> np.ndarray:
    """(2, n) pixel positions of a detection's track."""
    return np.array([[d.x], [d.y]]) + sign * trials.offsets[d.trial]


def merge(dets: list[Detection], trials: Trials, pl: Planes, dt: np.ndarray,
          sign: int = 1) -> list[Detection]:
    """Keep the strongest of each group of detections whose tracks overlap.

    A weaker track is also re-measured without the frames in which it passes within
    SHADOW_PX of a stronger kept track; if that leaves less than SHADOW_KEEP of its S/N,
    it was a side-lobe of the stronger object (a neighbouring trial crossing it) and goes.
    """
    kept: list[Detection] = []
    tracks: list[np.ndarray] = []
    for d in sorted(dets, key=lambda d: -d.snr):
        t = track_xy(trials, d, sign)
        if any(np.mean(np.hypot(*(t - k)) <= MERGE_PX) >= MERGE_SHARE for k in tracks):
            continue
        shadow = np.zeros(t.shape[1], bool)
        for k in tracks:
            shadow |= np.hypot(*(t - k)) <= SHADOW_PX
        if shadow.any():
            again = measure_track(pl, sign * trials.offsets[d.trial], d.x, d.y, dt, d.trial,
                                  exclude=shadow)
            if again.snr < SHADOW_KEEP * d.snr:
                continue
            d = again
        kept.append(d)
        tracks.append(t)
    return kept


def detect(pl: Planes, maps: SearchMaps, trials: Trials, dt: np.ndarray, threshold: float,
           mirror: bool = False) -> list[Detection]:
    """Merged, clipped detections from peaks of the raw map above `threshold`. Clipping can
    lower S/N, so callers cut on Detection.snr afterwards."""
    sign = -1 if mirror else 1
    dets = [measure_track(pl, sign * trials.offsets[maps.best_trial[y, x]], x, y, dt,
                          int(maps.best_trial[y, x]))
            for x, y in peaks(maps, threshold)]
    return merge(dets, trials, pl, dt, sign)
