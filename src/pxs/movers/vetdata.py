"""Vetting samples: stamps and simple features of one detection, for the learned filter and
the logistic-regression comparison (Stage 3). Pure numpy; the models live in probes.

Channels (4 x 15 x 15), each in units of its own noise: inverse-variance mean coadd along
the track, median coadd, coadd of the first half of the pass, coadd of the second half.
Features: S/N, unclipped minus clipped S/N, clipped-frame share, half-pass S/N shares,
largest single-frame share, track coverage, rate (px/day).
"""

from __future__ import annotations

import math
import warnings

import numpy as np

from .candidates import Detection, track_xy
from .core import CoreResult, rate_of
from .render import cutout

HALF = 7
FEATURES = ("snr", "clip_loss", "clipped_share", "first_share", "second_share",
            "max_frame_share", "n_frames_share", "rate")


def _coadd(core: CoreResult, xy: np.ndarray, use: np.ndarray, median: bool) -> np.ndarray:
    cuts, ws = [], []
    for i in np.flatnonzero(use):
        x, y = int(xy[0, i]), int(xy[1, i])
        d = cutout(core.cube.diff[i], x, y, HALF) / max(core.cube.template[i], 1e-6)
        v = cutout(core.cube.var[i], x, y, HALF) / max(core.cube.template[i], 1e-6) ** 2
        v = v * core.planes.noise_scale[i] ** 2
        cuts.append(d)
        ws.append(np.where(np.isfinite(v) & (v > 0), 1 / np.where(v > 0, v, 1), 0))
    if not cuts:
        return np.zeros((2 * HALF + 1,) * 2, np.float32)
    c, w = np.array(cuts), np.array(ws)
    ok = np.isfinite(c) & (w > 0)
    if median:  # all-NaN pixels (no frame covers them) are expected and come out as 0
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            m = np.nanmedian(np.where(ok, c, np.nan), axis=0)
            sig = np.sqrt(np.pi / 2 / np.maximum(ok.sum(0), 1) / np.where(
                ok.any(0), np.nanmean(np.where(ok, w, np.nan), 0), np.inf))
            return np.nan_to_num(m / sig).astype(np.float32)
    ws_ = np.where(ok, w, 0).sum(0)
    with np.errstate(all="ignore"):
        mean = np.where(ws_ > 0, (np.where(ok, w * c, 0)).sum(0) / ws_, 0)
        return np.nan_to_num(mean * np.sqrt(ws_)).astype(np.float32)


def sample(core: CoreResult, det: Detection, mirror: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(stamps (4, 15, 15), features (len(FEATURES),)) of one detection."""
    sign = -1 if mirror else 1
    xy = track_xy(core.trials, det, sign)
    n = len(core.cube)
    on = np.ones(n, bool)
    dt = core.geom.dt
    stamps = np.stack([_coadd(core, xy, on, False), _coadd(core, xy, on, True),
                       _coadd(core, xy, dt < 0, False), _coadd(core, xy, dt >= 0, False)])
    vx, vy, _ = rate_of(core, det)
    s = max(det.snr, 1e-6)
    feats = np.array([det.snr, det.snr_raw - det.snr, det.n_clipped / max(det.n_frames, 1),
                      det.snr_first / s, det.snr_second / s, det.max_frame_share,
                      det.n_frames / n, math.hypot(vx, vy)], np.float32)
    return stamps, feats
