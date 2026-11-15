"""Link the sources of all visits into tracks and fit each track's motion.

A seed is a pair of sources in visits at most SEED_GAP apart that a motion of up to
V_MAX_ARCSEC_YR could join. Seeds are tried slowest first, so the static sources claim their
own detections before a fast seed can string two different stars together. A seed is grown
visit by visit, nearest in time first: a straight line is fitted to the members, and the
nearest unclaimed source within the gate of its prediction joins. The gate is TOL_ARCSEC
plus 3 sigma of the prediction (with POS_SIGMA_ARCSEC per member, so it is wide while the
track is short and narrows as it grows), never more than MAX_GATE_ARCSEC. A track is kept
with at least MIN_DETECTIONS members over at least MIN_SPAN_YEARS: one or two residual
pairs are not enough.

Every source, static or not, becomes a track; whether it moved is decided afterwards from
the fitted motion and its error (`select`). The fit is weighted least squares of x and y
against time; the motion error is the formal one scaled up by the square root of the reduced
chi-square when that is above 1, so a track that scatters more than its visits' errors say
(a blend, a parallax, a ragged saturated core) has a correspondingly larger error.

Registration: the median residual of all tracks in a visit is that visit's offset against
the field's own sources; it is removed (with at least REG_MIN_TRACKS) and the tracks are
fitted again. Written with Claude Code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from pxs.fieldmovers.detect import Epochs

V_MAX_ARCSEC_YR = 12.0  # Barnard's Star, the fastest star in the sky, moves 10.4
SEED_GAP = 2
TOL_ARCSEC = 2.0
POS_SIGMA_ARCSEC = 0.5
MAX_GATE_ARCSEC = 15.0
MIN_DETECTIONS = 6
MIN_SPAN_YEARS = 3.0
REG_MIN_TRACKS = 5


@dataclass(frozen=True)
class Track:
    """A linked source: position (x0, y0) px at year t0, motion px/yr, 1-sigma errors."""

    t0: float
    x0: float
    y0: float
    vx: float
    vy: float
    err_xy0: float
    err_v: float
    chi2: float  # reduced
    snr: float  # median over the visits it was seen in
    epochs: tuple[int, ...]  # indices into Epochs.years
    members: tuple[int, ...]  # index of the source within each of those visits

    def at(self, year: float) -> tuple[float, float]:
        dt = year - self.t0
        return self.x0 + self.vx * dt, self.y0 + self.vy * dt

    @property
    def significance(self) -> float:
        return math.hypot(self.vx, self.vy) / self.err_v


def fit(t: np.ndarray, xy: np.ndarray, err: np.ndarray) -> tuple[float, ...]:
    """(t0, x0, y0, vx, vy, err_xy0, err_v, reduced chi2) of a straight line through xy(t)."""
    w = 1.0 / err**2
    sw = float(w.sum())
    t0 = float((w * t).sum() / sw)
    tau = t - t0
    stt = max(float((w * tau * tau).sum()), 1e-12)
    x0, y0 = (float((w * xy[:, k]).sum() / sw) for k in (0, 1))
    vx, vy = (float((w * tau * xy[:, k]).sum() / stt) for k in (0, 1))
    res2 = (xy[:, 0] - x0 - vx * tau) ** 2 + (xy[:, 1] - y0 - vy * tau) ** 2
    dof = 2 * t.size - 4
    chi2 = float((w * res2).sum() / dof) if dof > 0 else 1.0
    scale = max(1.0, math.sqrt(chi2))
    return t0, x0, y0, vx, vy, scale / math.sqrt(sw), scale / math.sqrt(stt), chi2


def _seeds(ep: Epochs) -> list[tuple[float, int, int, int, int]]:
    """(speed px/yr, epoch a, source a, epoch b, source b), slowest first."""
    out = []
    vmax, tol = V_MAX_ARCSEC_YR / ep.pixscale_arcsec, TOL_ARCSEC / ep.pixscale_arcsec
    for a in range(len(ep.years)):
        for b in range(a + 1, min(a + SEED_GAP, len(ep.years) - 1) + 1):
            dt = float(ep.years[b] - ep.years[a])
            if dt <= 0.0 or not ep.xy[a].size or not ep.xy[b].size:
                continue
            d = np.hypot(*(ep.xy[a][:, None, :] - ep.xy[b][None, :, :]).transpose(2, 0, 1))
            for i, j in zip(*np.nonzero(d <= vmax * dt + tol)):
                out.append((float(d[i, j]) / dt, a, int(i), b, int(j)))
    return sorted(out)


def _line(ep: Epochs, members: dict[int, int]) -> tuple[float, ...]:
    ks = sorted(members)
    return fit(ep.years[ks], np.array([ep.xy[k][members[k]] for k in ks]),
               np.array([ep.err_px[k][members[k]] for k in ks]))


def _gate(ep: Epochs, members: dict[int, int], line: tuple[float, ...], year: float) -> float:
    """Radius (px) around the prediction at `year` within which a source may join."""
    ks = sorted(members)
    tau = ep.years[ks] - float(np.mean(ep.years[ks]))
    lever = (year - float(np.mean(ep.years[ks]))) ** 2 / max(float((tau**2).sum()), 1e-12)
    sigma = POS_SIGMA_ARCSEC * math.sqrt(1.0 / len(ks) + lever)
    return min(MAX_GATE_ARCSEC, TOL_ARCSEC + 3.0 * sigma) / ep.pixscale_arcsec


def _grow(ep: Epochs, seed: tuple[float, int, int, int, int],
          free: list[np.ndarray]) -> dict[int, int]:
    """Members {epoch: source} of the track grown from `seed` out of the unclaimed sources."""
    _, a, i, b, j = seed
    members = {a: i, b: j}
    mid = 0.5 * float(ep.years[a] + ep.years[b])
    others = sorted((k for k in range(len(ep.years)) if k not in members),
                    key=lambda k: abs(float(ep.years[k]) - mid))
    for k in others:
        if not free[k].any():
            continue
        line = _line(ep, members)
        px, py = line[1] + line[3] * (ep.years[k] - line[0]), line[2] + line[4] * (ep.years[k] - line[0])
        d = np.where(free[k], np.hypot(ep.xy[k][:, 0] - px, ep.xy[k][:, 1] - py), np.inf)
        n = int(np.argmin(d))
        if d[n] <= _gate(ep, members, line, float(ep.years[k])):
            members[k] = n
    return members


def _track(ep: Epochs, members: dict[int, int]) -> Track:
    ks = sorted(members)
    line = _line(ep, members)
    snr = float(np.median([ep.snr[k][members[k]] for k in ks]))
    return Track(*line, snr=snr, epochs=tuple(ks), members=tuple(members[k] for k in ks))


def _registered(ep: Epochs, tracks: list[Track]) -> Epochs:
    """`ep` with each visit's median residual against the tracks removed."""
    res: list[list[tuple[float, float]]] = [[] for _ in ep.years]
    for tr in tracks:
        for k, m in zip(tr.epochs, tr.members):
            px, py = tr.at(float(ep.years[k]))
            res[k].append((ep.xy[k][m, 0] - px, ep.xy[k][m, 1] - py))
    shift = [np.median(np.array(r), axis=0) if len(r) >= REG_MIN_TRACKS else np.zeros(2)
             for r in res]
    return Epochs(band=ep.band, ids=ep.ids, years=ep.years,
                  xy=tuple(xy - s for xy, s in zip(ep.xy, shift)), snr=ep.snr,
                  err_px=ep.err_px, pixscale_arcsec=ep.pixscale_arcsec, size_px=ep.size_px)


def tracks(ep: Epochs) -> list[Track]:
    """Every source followed through at least MIN_DETECTIONS visits, registered and fitted."""
    free = [np.ones(len(s), bool) for s in ep.snr]
    kept: list[dict[int, int]] = []
    for seed in _seeds(ep):
        _, a, i, b, j = seed
        if not (free[a][i] and free[b][j]):
            continue
        members = _grow(ep, seed, free)
        ks = sorted(members)
        if len(ks) < MIN_DETECTIONS or ep.years[ks[-1]] - ep.years[ks[0]] < MIN_SPAN_YEARS:
            continue
        kept.append(members)
        for k, m in members.items():
            free[k][m] = False
    reg = _registered(ep, [_track(ep, m) for m in kept])
    return [_track(reg, m) for m in kept]
