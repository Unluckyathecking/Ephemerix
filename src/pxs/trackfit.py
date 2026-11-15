"""Motion of a target too faint to find in any single frame, fitted on all frames at once.

`centroid.detect` needs the target at S/N 5 in a frame. A W2 14.7-15 object next to other
sources reaches 3-5 per NEOWISE visit (CWISE J0411+4714: a peak at the predicted place in
22 of 22 visits, S/N 3.0-4.9), so every visit is "not detected" and no motion is measured,
although the visits together hold it at S/N 40. Here one source moving in a straight line is
fitted to the pixels of every W2 visit together: brightness, position at the mean epoch and
velocity are free (five numbers for the whole series), the PSF is a Gaussian of the band's
width, each frame keeps its own background level. Catalogued neighbours whose light reaches
the fitted area are in the model at their catalogue positions with free brightness.

The catalogue motion only decides which pixels are fitted and where the fit starts. Three
checks make the answer the data's own, and the result is None unless all hold:
- the fitted brightness is at least `centroid.SNR_MIN` times its error;
- started from zero motion instead of the catalogue motion, the fit ends at the same motion
  (START_AGREE_SIGMA): next to a much brighter star it does not (CWISE J2021+1524, 14" from
  a W2 9.2 star: -403 against -57 mas/yr), and nothing is reported;
- the source stays within MAX_SHIFT_FWHM of the predicted place, so it is not a neighbour.
These checks do not protect empty sky in the wings of a much brighter star, where a Gaussian
finds "sources" that pass all three; `trackmotion` refuses those places before fitting.

Errors are the formal ones times the native pixel size over the grid's (resampled pixels are
not independent, as in `centroid`), times sqrt(reduced chi2) when that exceeds 1, times
ERR_SCALE. ERR_SCALE is measured, not assumed, and it was set after CWISE J0623+0715 had
come out 3.9 sigma from its catalogue motion without it. One command, `planted_movers.py
both` on four fields (probes/astro/planted_movers.py): 165 movers of the targets' brightness
planted with the real PSF (a scaled, shifted bright star of the same frame) in the real W2
visits, 81 at random places and 84 passing 9" from a 1.55 times brighter real source. 162
were measured; the motion error along the track has median +5 mas/yr (no bias), but its rms
is 1.75 times the unscaled error (robust 1.4; 1.5 at random places and 1.9 beside the
neighbour when run apart): faint sources that are not in the model. With ERR_SCALE = 1.7,
2.2% of the components lie beyond 3 sigma. J0623+0715 agrees at any scale above 1.3.

Also checked on real W2 visits, same probe: 41 static CatWISE sources of the targets'
brightness in three fields come out at zero motion (rms of motion/error 0.45, largest 1.2);
with the epochs of the visits shuffled the fit is worse than with the true order in 40 of
40 shuffles for J0411+4714 and for J0623+0715 (also tests/test_astro_trackfit.py).

Pixels use pixel edges (docs/api.md); x grows west and y south on the north-up grid, so
pmra = -vx and pmdec = -vy. Years are decimal. Written with Claude Code.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

log = logging.getLogger(__name__)

MIN_FRAMES = 8
MIN_BASELINE_YEARS = 5.0
START_AGREE_SIGMA = 1.0
MAX_SHIFT_FWHM = 0.5
MIN_USABLE = 0.9  # share of the fitted pixels that must be good in every frame
ERR_SCALE = 1.7  # stated errors against the scatter of planted movers (module docstring)
FWHM_PER_SIGMA = 2.3548

Point = tuple[float, float]


@dataclass(frozen=True)
class Frames:
    """Background-subtracted frames on one grid: resid and usable are (n, ny, nx), noise and
    years (n,). shift_px (n, 2) is a known displacement of the target in each frame (its
    parallax), added to the straight line."""

    resid: np.ndarray
    usable: np.ndarray
    noise: np.ndarray
    years: np.ndarray
    shift_px: np.ndarray


@dataclass(frozen=True)
class TrackFit:
    """Position at the mean epoch (edge px), velocity (px/yr), their 1-sigma errors, the
    brightness S/N, reduced chi2 and the number of frames."""

    x: float
    y: float
    vx: float
    vy: float
    err_v: Point
    snr: float
    reduced_chi2: float
    n_frames: int


def _window(fr: Frames, seed_xy: Point, seed_v: Point, half: int) -> tuple[slice, slice]:
    """The box of pixels fitted in every frame: the seed track's extent plus `half`."""
    tau = fr.years - fr.years.mean()
    xs = [seed_xy[0] + seed_v[0] * t for t in (tau.min(), tau.max())]
    ys = [seed_xy[1] + seed_v[1] * t for t in (tau.min(), tau.max())]
    ny, nx = fr.resid.shape[1:]
    return (slice(max(int(min(ys)) - half, 0), min(int(max(ys)) + half + 1, ny)),
            slice(max(int(min(xs)) - half, 0), min(int(max(xs)) + half + 1, nx)))


def _residuals(fr: Frames, sl, sigma_px: float, static: Sequence[Point]):
    """Function of the parameters (x0, y0, vx, vy, brightness, one brightness per static
    neighbour) giving the noise-weighted residuals, each frame's mean removed."""
    ii, jj = np.mgrid[sl]
    xx, yy = jj + 0.5, ii + 0.5
    z, ok = fr.resid[:, sl[0], sl[1]], fr.usable[:, sl[0], sl[1]]
    n_ok = np.maximum(ok.sum(axis=(1, 2), keepdims=True), 1)
    tau = fr.years - fr.years.mean()
    shapes = [np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px**2)) for x, y in static]

    def residuals(p: np.ndarray) -> np.ndarray:
        fixed = sum((a * s for a, s in zip(p[5:], shapes)), np.zeros(xx.shape))
        x = p[0] + p[2] * tau + fr.shift_px[:, 0]
        y = p[1] + p[3] * tau + fr.shift_px[:, 1]
        r2 = (xx[None] - x[:, None, None]) ** 2 + (yy[None] - y[:, None, None]) ** 2
        r = np.where(ok, z - p[4] * np.exp(-r2 / (2 * sigma_px**2)) - fixed[None], 0.0)
        r = np.where(ok, r - r.sum(axis=(1, 2), keepdims=True) / n_ok, 0.0)
        return (r / fr.noise[:, None, None]).ravel()

    return residuals, int(ok.sum()), float(ok.mean(axis=(1, 2)).min())


def _solve(fr: Frames, sl, sigma_px, seed_xy, seed_v, static, inflate):
    """(parameters, their 1-sigma errors, reduced chi2) from one start, or None."""
    residuals, n_px, usable = _residuals(fr, sl, sigma_px, static)
    if usable < MIN_USABLE:
        return None
    i, j = int(seed_xy[1]), int(seed_xy[0])
    amp = max(float(np.mean(fr.resid[:, i, j])), float(np.median(fr.noise)))
    p0 = np.array([seed_xy[0], seed_xy[1], seed_v[0], seed_v[1], amp, *([amp] * len(static))])
    dof = n_px - p0.size - fr.years.size
    if dof <= 0:
        return None
    try:
        res = least_squares(residuals, p0, method="lm", max_nfev=600)
        cov = np.linalg.pinv(res.jac.T @ res.jac)
    except (ValueError, np.linalg.LinAlgError) as exc:
        log.info("all-frames fit failed: %s", exc)
        return None
    if not res.success:
        return None
    red = float(np.sum(res.fun**2)) / dof
    err = np.sqrt(np.abs(np.diag(cov))) * inflate * math.sqrt(max(1.0, red)) * ERR_SCALE
    return res.x, err, red


def fit(fr: Frames, sigma_px: float, seed_xy: Point, seed_v: Point,
        static: Sequence[Point] = (), half: int = 11, inflate: float = 1.0,
        snr_min: float = 5.0) -> TrackFit | None:
    """Fit one moving source to all frames (module docstring). `seed_xy`: predicted position
    at the mean epoch; `seed_v`: catalogue velocity (px/yr); `static`: neighbours' positions;
    `half`: half-width of the fitted box around the track; `inflate`: error factor for
    resampled pixels. None when there are too few frames, the predicted place is off the
    frame or closer than `half` to its edge, or a check fails."""
    if fr.years.size < MIN_FRAMES or np.ptp(fr.years) < MIN_BASELINE_YEARS:
        return None
    ny, nx = fr.resid.shape[1:]
    if not (half <= seed_xy[0] < nx - half and half <= seed_xy[1] < ny - half):
        return None
    sl = _window(fr, seed_xy, seed_v, half)
    a = _solve(fr, sl, sigma_px, seed_xy, seed_v, static, inflate)
    b = _solve(fr, sl, sigma_px, seed_xy, (0.0, 0.0), static, inflate)
    if a is None or b is None:
        return None
    p, err, red = a
    if err[4] <= 0 or p[4] / err[4] < snr_min:
        return None
    if math.hypot(p[0] - seed_xy[0], p[1] - seed_xy[1]) > MAX_SHIFT_FWHM * FWHM_PER_SIGMA * sigma_px:
        return None
    if any(abs(p[k] - b[0][k]) > START_AGREE_SIGMA * err[k] for k in (2, 3)):
        return None
    return TrackFit(float(p[0]), float(p[1]), float(p[2]), float(p[3]),
                    (float(err[2]), float(err[3])), float(p[4] / err[4]), red, fr.years.size)
