"""Fit the target and its close neighbours at the same time.

`centroid._fit` fits ONE Gaussian to the pixels in a box around the target. A second source
whose light reaches that box pulls the fitted position towards it (fitblend.py: WISE
1541-2250 measured up to 2" off its track; CWISE 1055+5443 0.4-0.7" north while a W2 15.0
source sat 10.5-12.5" north). Here each neighbour the caller names (`centroid._joint_fit`:
the frame's other peaks near the target, and catalogued sources the smoothed map merges
with it) gets its own Gaussian: one amplitude and position each, one shared width and one
shared background level, fitted to the pixels in the boxes around all of them.

The fit is refused (None, and the caller keeps the single-source fit) when any fitted source
ends more than `max_shift_px` from where it was started, any amplitude is not positive, a
neighbour ends closer to the target than `min_sep_px`, or it comes out more than
MAX_FLUX_RATIO times as bright as the target: the model is then not describing the sources
it was started on, or the pair is outside what was checked.

Checked on pairs planted in real frames (probes/astro/planted_pairs.py): a scaled copy of the
frame is added at a known offset, so the neighbour has the real PSF and noise, and the peak
nearest the star is measured as `centroid.detect` would. 10 isolated stars of S/N 7-40,
three fields, six visits, four directions: about 240 cases per line. Median shift of the
star towards the neighbour in arcsec, single fit -> joint fit, for a neighbour 0.3, 0.6 and
1.0 times as bright:
    W2   9": +0.49 -> +0.07   +1.83 -> +0.01   +4.47 -> -0.03
        10": +0.31 -> -0.01   +1.00 ->  0.00   +4.46 -> +0.02
        12": +0.12 -> -0.01   +0.24 ->  0.00   +0.46 -> +0.04
        16": +0.02 ->  0.00   +0.04 -> +0.02   +0.05 -> +0.02
    W1   9": +0.31 ->  0.00   +1.11 -> +0.01   +4.21 -> +0.05
        12": +0.07 -> +0.01   +0.14 -> +0.02   +0.22 -> +0.05
The shift over its stated error has a robust rms of 0.3-1.3, so the errors hold. At 8" the
joint fit is refused in most cases and leaves +0.2 to -0.6" in the rest (MIN_SEP_FWHM). A
neighbour 1.5 or 2 times as bright passes the brightness limit in one case in ten, shifted
by 0.5-1.7": such neighbours are kept out before the fit (`centroid._joint_fit` for peaks,
`fitblend.neighbours_px` for catalogued sources). SPHEREx frames were not tested.

Pixel coordinates use pixel edges: array element [i, j] has its centre at (j + 0.5, i + 0.5).
Written with Claude Code.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit

log = logging.getLogger(__name__)

MAX_NEIGHBOURS = 2  # the nearest ones; more free sources than this is a crowded field
# A neighbour's light reaches the target's fitting box when its centre is within the box
# half-width plus REACH_FWHM PSF widths of the target.
REACH_FWHM = 1.0
MIN_SEP_FWHM = 1.2  # 8.8" in W2: closer pairs are not separated reliably (module docstring)
MAX_FLUX_RATIO = 1.25  # equal brightness, with room for noise: brighter was not unbiased

Point = tuple[float, float]


@dataclass(frozen=True)
class PairFit:
    """Target position (edge px), its formal 1-sigma errors, amplitude, the shared Gaussian
    sigma, and the fitted neighbour positions."""

    x: float
    y: float
    sx: float
    sy: float
    amplitude: float
    sigma: float
    neighbours: tuple[Point, ...]


def _model(n_sources: int):
    def f(xy, *p):
        x, y = xy
        sigma, offset = p[-2], p[-1]
        out = np.full(x.shape, offset, dtype=float)
        for k in range(n_sources):
            amp, x0, y0 = p[3 * k: 3 * k + 3]
            out = out + amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma**2))
        return out

    return f


def _pixels(usable: np.ndarray, centres: Sequence[Point], half: int) -> np.ndarray:
    """Usable pixels inside the box of half-width `half` around any of the centres."""
    ny, nx = usable.shape
    pick = np.zeros(usable.shape, bool)
    for x, y in centres:
        i0, j0 = int(y), int(x)
        pick[max(i0 - half, 0): min(i0 + half + 1, ny),
             max(j0 - half, 0): min(j0 + half + 1, nx)] = True
    return pick & usable


def fit(resid: np.ndarray, usable: np.ndarray, noise: float, sigma_px: float, half: int,
        target: Point, neighbours: Sequence[Point], max_shift_px: float,
        min_sep_px: float = 0.0) -> PairFit | None:
    """Joint Gaussian fit of the target and up to MAX_NEIGHBOURS neighbours (nearest first).

    `resid` is the background-subtracted frame, `usable` its good pixels, `noise` the pixel
    noise, `half` the box half-width in pixels. Returns None when there is no neighbour, the
    fit fails, or it is refused (module docstring).
    """
    near = sorted(neighbours, key=lambda p: math.hypot(p[0] - target[0], p[1] - target[1]))
    centres = [target, *near[:MAX_NEIGHBOURS]]
    if len(centres) < 2:
        return None
    pick = _pixels(usable, centres, half)
    if pick.sum() < 8 * len(centres):
        return None
    ii, jj = np.nonzero(pick)
    z = resid[pick]
    p0: list[float] = []
    for x, y in centres:
        i = min(max(int(y), 0), resid.shape[0] - 1)
        j = min(max(int(x), 0), resid.shape[1] - 1)
        p0 += [max(float(resid[i, j]), noise), x, y]
    p0 += [sigma_px, 0.0]
    try:
        p, cov = curve_fit(_model(len(centres)), (jj + 0.5, ii + 0.5), z, p0=p0,
                           sigma=np.full(z.shape, noise), absolute_sigma=True, maxfev=8000)
    except (RuntimeError, ValueError) as exc:
        log.info("joint centroid fit failed: %s", exc)
        return None
    err = np.sqrt(np.abs(np.diag(cov)))
    if not np.all(np.isfinite(p)) or not np.all(np.isfinite(err[1:3])):
        return None
    for k, (x, y) in enumerate(centres):
        amp, x0, y0 = p[3 * k: 3 * k + 3]
        if amp <= 0 or math.hypot(x0 - x, y0 - y) > max_shift_px:
            return None
        if k and (math.hypot(x0 - p[1], y0 - p[2]) < min_sep_px or amp > MAX_FLUX_RATIO * p[0]):
            return None
    fitted = tuple((float(p[3 * k + 1]), float(p[3 * k + 2])) for k in range(1, len(centres)))
    return PairFit(float(p[1]), float(p[2]), float(err[1]), float(err[2]), float(p[0]),
                   abs(float(p[-2])), fitted)
