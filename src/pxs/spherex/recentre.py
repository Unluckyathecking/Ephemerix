"""One common position correction per pass for the forced photometry.

The flux is a PSF amplitude at a predicted position. A miss of 0.2 SPHEREx px loses 7-13%
of the flux and 0.3 px 15-25%, more at short wavelengths, so the spectrum reddens.
Here one sky offset (east, north, arcsec) common to
every exposure of a pass is fitted by maximising the summed PSF-fit chi2 improvement
S(offset) = sum_i (sum w p d)^2 / (sum w p^2) over the pass's high-S/N exposures, on a
coarse grid and then a fine one. Each exposure maps the sky offset to its own pixel
offset through its WCS, so frames at different roll angles share one correction. The
background and the fitted pixels are fixed at the predicted position, so every trial
offset is compared on the same data.

The offset is applied only when all of these hold (otherwise reason says why not):
- at least MIN_EXPOSURES exposures (at most MAX_PER_HALF per half are fitted, best S/N
  first) with S/N >= MIN_SNR_EACH at the predicted position,
  and their S/N added in quadrature (empty-position error scale applied) >= MIN_SNR_SUM;
- the 1-sigma uncertainty is at most MAX_ERR_PX on each axis. It is the formal error
  (curvature of S, times the pass's error scale), raised to half the difference between
  the offsets fitted separately to the short and long arrays when both have the signal
  (a measured systematic: PSF model and colour), and never below ERR_FLOOR_ARCSEC;
- the best offset is inside the cap and not on its edge (an optimum on the edge means the
  fit is being pulled by something else). The cap is CAP_PX (one SPHEREx pixel) when the
  caller passes the catalogued neighbours, and the tighter SAFE_CAP_PX when it does not;
- no catalogued neighbour lies within NEIGHBOUR_PX of the predicted position, and the
  corrected position is not closer to any neighbour than the prediction was;
- when the short (D1-D3) and long (D4-D6) arrays each have enough signal on their own,
  their separate offsets agree to COLOUR_SIGMA sigma or COLOUR_TOL_PX. Without
  catalogue neighbours this is the guard against a blended star of another colour.

Measured on real passes (docs in the PR): bright T dwarfs move by 0.0-0.8 arcsec and gain
0-5% of flux; a deliberate 0.3 px error costs 5-33% and is recovered to < 1%.

Units: offsets in arcsec on the sky (east = +RA), pixels are native SPHEREx pixels.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from . import config
from .photometry import bilinear, clipped_median, good_mask, measure, radius
from .read import Stamp

MIN_SNR_EACH = 5.0
MIN_EXPOSURES = 3
MIN_SNR_SUM = 15.0
MAX_ERR_PX = 0.1
CAP_PX = 1.0
SAFE_CAP_PX = 0.5
NEIGHBOUR_PX = 2.0
COARSE_STEP_PX = 0.1
FINE_HALF_PX, FINE_STEP_PX = 0.15, 0.025
BLUE_LAST_DETECTOR = 3  # D1-D3 cover 0.75-2.42 um, D4-D6 2.42-5.0 um
COLOUR_SIGMA, COLOUR_TOL_PX = 3.0, 0.15
MAX_PER_HALF = 30  # exposures per half fitted (by S/N), to bound the run time
ERR_FLOOR_ARCSEC = 0.02  # never report a zero uncertainty
_FIT_EXTRA_PX = 1.0  # fitted pixels: within R_FIT + this of the prediction

Sky = tuple[float, float]  # (ra, dec) in degrees


@dataclass(frozen=True)
class Recentre:
    """Fitted offset of a pass (arcsec east and north) and whether it was applied."""

    east_arcsec: float
    north_arcsec: float
    err_east_arcsec: float
    err_north_arcsec: float
    applied: bool
    reason: str  # "" when applied, else why not
    n_used: int
    snr: float  # quadrature sum of the exposures used, errors scaled

    @property
    def offset_arcsec(self) -> float:
        return math.hypot(self.east_arcsec, self.north_arcsec)

    def as_dict(self) -> dict:
        r = lambda v: None if not math.isfinite(v) else round(float(v), 3)
        return {"east_arcsec": r(self.east_arcsec), "north_arcsec": r(self.north_arcsec),
                "err_east_arcsec": r(self.err_east_arcsec),
                "err_north_arcsec": r(self.err_north_arcsec), "applied": self.applied,
                "reason": self.reason, "n_used": self.n_used, "snr": r(self.snr)}


NONE = Recentre(0.0, 0.0, math.nan, math.nan, False, "no exposures", 0, 0.0)


def _not_applied(reason: str, n: int = 0, snr: float = 0.0, off=(0.0, 0.0),
                 err=(math.nan, math.nan)) -> Recentre:
    return Recentre(float(off[0]), float(off[1]), float(err[0]), float(err[1]), False, reason,
                    n, float(snr))


def sky_to_pixel_jacobian(s: Stamp) -> np.ndarray:
    """2x2 matrix J with (dx, dy) px = J @ (east, north) arcsec at the stamp's target."""
    w = s.wcs()
    ra, dec = (float(v) for v in w.pixel_to_world_values(s.xpix - s.x0, s.ypix - s.y0))
    step = 1.0 / 3600.0
    cols = []
    for dra, ddec in ((step / math.cos(math.radians(dec)), 0.0), (0.0, step)):
        x, y = w.world_to_pixel_values(ra + dra, dec + ddec)
        cols.append((float(x) + s.x0 - s.xpix, float(y) + s.y0 - s.ypix))
    return np.array(cols).T


def pixel_offset(s: Stamp, east: float, north: float, jac: np.ndarray | None = None) -> tuple[float, float]:
    """Pixel offset (dx, dy) in this stamp of a sky offset in arcsec."""
    j = sky_to_pixel_jacobian(s) if jac is None else jac
    dx, dy = j @ np.array([east, north])
    return float(dx), float(dy)


@dataclass(frozen=True)
class _Fit:
    """Fixed data of one exposure for the offset search (fitted pixels only)."""

    stamp: Stamp
    jac: np.ndarray
    xx: np.ndarray  # full-frame column of each fitted pixel
    yy: np.ndarray  # full-frame row
    d: np.ndarray  # background-subtracted data, MJy/sr
    w: np.ndarray  # 1 / variance


def _prepare(s: Stamp) -> _Fit | None:
    r = radius(s, s.xpix, s.ypix)
    good = good_mask(s)
    img = s.image - s.zodi
    ann = good & (r >= config.R_ANNULUS[0]) & (r < config.R_ANNULUS[1])
    use = good & (r <= config.R_FIT + _FIT_EXTRA_PX)
    if ann.sum() < 10 or use.sum() < 4 or s.psf is None:
        return None
    yy, xx = np.nonzero(use)
    d = img[use] - clipped_median(img[ann])
    return _Fit(s, sky_to_pixel_jacobian(s), xx + s.x0, yy + s.y0, d, 1.0 / s.variance[use])


def _gain(f: _Fit, east: float, north: float) -> float:
    """Chi2 improvement of a PSF at the offset over no source, with the amplitude free."""
    dx, dy = f.jac @ np.array([east, north])
    o, c = config.EPSF_OVERSAMPLE, (config.EPSF_SIZE - 1) / 2
    x, y = f.stamp.xpix + dx, f.stamp.ypix + dy
    p = bilinear(f.stamp.psf, c + o * (f.yy - y), c + o * (f.xx - x), 0.0)
    den = float(np.sum(f.w * p * p))
    return 0.0 if den <= 0 else float(np.sum(f.w * p * f.d)) ** 2 / den


def summed_gain(fits: Sequence[_Fit], east: float, north: float) -> float:
    """Summed chi2 improvement over the exposures for one sky offset (arcsec)."""
    return sum(_gain(f, east, north) for f in fits)


def _grid_max(fits: Sequence[_Fit], centre: tuple[float, float], half: float,
              step: float) -> tuple[float, float]:
    """Offset of the largest summed gain on a square grid around `centre` (arcsec)."""
    ax = np.arange(-half, half + 0.5 * step, step)
    trials = [(centre[0] + de, centre[1] + dn) for de in ax for dn in ax]
    return max(trials, key=lambda t: summed_gain(fits, *t))


def _newton(fits: Sequence[_Fit], at: tuple[float, float],
            h: float) -> tuple[tuple[float, float], np.ndarray | None]:
    """One Newton step on chi2 = const - S from `at`, and the offset covariance (arcsec^2).

    The covariance is the inverse of the Fisher matrix chi2'' / 2 (chi2 / 2 = -ln L).
    """
    def s(de: float, dn: float) -> float:
        return summed_gain(fits, at[0] + de, at[1] + dn)

    s0 = s(0, 0)
    se, sw, sn, ss = s(h, 0), s(-h, 0), s(0, h), s(0, -h)
    grad = -np.array([se - sw, sn - ss]) / (2 * h)  # of chi2
    a = (2 * s0 - se - sw) / h**2
    b = (2 * s0 - sn - ss) / h**2
    c = -(s(h, h) - s(h, -h) - s(-h, h) + s(-h, -h)) / (4 * h * h)
    hess = np.array([[a, c], [c, b]])
    if a <= 0 or b <= 0 or np.linalg.det(hess) <= 0:
        return at, None
    step = -np.linalg.solve(hess, grad)
    if np.hypot(*step) > h:  # outside the region the quadratic describes
        return at, np.linalg.inv(0.5 * hess)
    return (at[0] + float(step[0]), at[1] + float(step[1])), np.linalg.inv(0.5 * hess)


def _locate(fits: Sequence[_Fit], cap_arcsec: float) -> tuple[tuple[float, float], np.ndarray | None]:
    """Best common offset within the cap (coarse grid, fine grid, Newton step)."""
    pix = config.PIXSCALE_ARCSEC
    coarse = _grid_max(fits, (0.0, 0.0), cap_arcsec, COARSE_STEP_PX * pix)
    fine = _grid_max(fits, coarse, FINE_HALF_PX * pix, FINE_STEP_PX * pix)
    return _newton(fits, fine, 2 * FINE_STEP_PX * pix)


def _neighbour_px(pos_east_north: Sequence[tuple[float, float]], east: float, north: float) -> list[float]:
    return [math.hypot(e - east, n - north) / config.PIXSCALE_ARCSEC for e, n in pos_east_north]


def _offsets_of(neighbours: Sequence[Sky], ra: float, dec: float) -> list[tuple[float, float]]:
    """(east, north) arcsec of each neighbour from (ra, dec), small-angle."""
    cosd = math.cos(math.radians(dec))
    return [(((nra - ra + 180.0) % 360.0 - 180.0) * cosd * 3600.0, (ndec - dec) * 3600.0)
            for nra, ndec in neighbours]


def _select(stamps: Sequence[Stamp], scale: float) -> list[tuple[_Fit, float]]:
    """Exposures with S/N >= MIN_SNR_EACH at the prediction (errors scaled), with that S/N."""
    out = []
    for s in stamps:
        m = measure(s)
        if not (m.ok and m.err_mjy > 0):
            continue
        z = m.flux_mjy / (m.err_mjy * scale)
        if z >= MIN_SNR_EACH and (f := _prepare(s)) is not None:
            out.append((f, z))
    return out


def _quad_snr(chosen: Sequence[tuple[_Fit, float]]) -> float:
    return math.sqrt(sum(z * z for _, z in chosen))


def _enough(chosen: Sequence[tuple[_Fit, float]]) -> bool:
    return len(chosen) >= MIN_EXPOSURES and _quad_snr(chosen) >= MIN_SNR_SUM


def _errors(cov: np.ndarray | None, scale: float) -> tuple[float, float]:
    if cov is None:
        return math.nan, math.nan
    return scale * math.sqrt(cov[0, 0]), scale * math.sqrt(cov[1, 1])


def _halves(chosen: Sequence[tuple[_Fit, float]]) -> list[list[tuple[_Fit, float]]]:
    """Short (D1-D3) and long (D4-D6) exposures, each cut to its MAX_PER_HALF best by S/N."""
    out = []
    for blue in (True, False):
        h = [c for c in chosen if (c[0].stamp.detector <= BLUE_LAST_DETECTOR) == blue]
        out.append(sorted(h, key=lambda c: -c[1])[:MAX_PER_HALF])
    return out


def _colour_check(halves: Sequence[Sequence[tuple[_Fit, float]]], cap: float,
                  scale: float) -> tuple[bool, tuple[float, float] | None]:
    """(split, half the short-minus-long offset difference per axis in arcsec, or None).

    Only when both halves have enough signal on their own. Split is True when their
    offsets differ by more than COLOUR_SIGMA sigma and COLOUR_TOL_PX: the light at the two
    ends of the spectrum does not come from one point, as when a star of another colour is
    blended with the target.
    """
    if not all(_enough(h) for h in halves):
        return False, None
    (pb, cb), (pr, cr) = (_locate([f for f, _ in h], cap) for h in halves)
    eb, er = _errors(cb, scale), _errors(cr, scale)
    diff = math.hypot(pb[0] - pr[0], pb[1] - pr[1])
    sig = math.sqrt(float(np.nansum([v * v for v in (*eb, *er)])))
    split = diff > max(COLOUR_SIGMA * sig, COLOUR_TOL_PX * config.PIXSCALE_ARCSEC)
    return split, (abs(pb[0] - pr[0]) / 2, abs(pb[1] - pr[1]) / 2)


def _honest(err: tuple[float, float], half_diff: tuple[float, float] | None) -> tuple[float, float]:
    """Formal error, raised to half the short/long disagreement and to ERR_FLOOR_ARCSEC."""
    hd = half_diff or (0.0, 0.0)
    return tuple(max(e, h, ERR_FLOOR_ARCSEC) for e, h in zip(err, hd))  # type: ignore[return-value]


def _neighbour_reason(neighbours: Sequence[Sky] | None, target_sky: Sky | None,
                      best: tuple[float, float] | None) -> str:
    """Why catalogued neighbours forbid the offset ("" when they do not)."""
    if neighbours is None or target_sky is None:
        return ""
    near = _offsets_of(neighbours, *target_sky)
    if not near:
        return ""
    now = min(_neighbour_px(near, 0.0, 0.0))
    if best is None:
        return "catalogued neighbour nearby" if now < NEIGHBOUR_PX else ""
    return "offset points towards a neighbour" if min(_neighbour_px(near, *best)) < now else ""


def fit_offset(stamps: Sequence[Stamp], scale: float = 1.0,
               neighbours: Sequence[Sky] | None = None, target_sky: Sky | None = None) -> Recentre:
    """Fit and judge one common sky offset for the exposures of a pass (see module doc).

    Args:
        stamps: the pass's stamps, centred on the predicted position.
        scale: the pass's empirical error scale (>= 1), applied to S/N and the uncertainty.
        neighbours: catalogued sources other than the target (ra, dec deg) at the pass
            epoch, or None when the caller has none (a tighter cap is then used).
        target_sky: predicted (ra, dec) of the target at the pass, needed with neighbours.
    """
    chosen = _select(stamps, scale)
    n, snr = len(chosen), _quad_snr(chosen)
    if not _enough(chosen):
        return _not_applied("too faint to locate", n, snr)
    if reason := _neighbour_reason(neighbours, target_sky, None):
        return _not_applied(reason, n, snr)
    pix = config.PIXSCALE_ARCSEC
    cap = (CAP_PX if neighbours is not None else SAFE_CAP_PX) * pix
    halves = _halves(chosen)
    used = [c for h in halves for c in h]
    best, cov = _locate([f for f, _ in used], cap)
    if math.hypot(*best) > cap - COARSE_STEP_PX * pix:
        return _not_applied("offset reached the limit", n, snr, best, _errors(cov, scale))
    split, half_diff = _colour_check(halves, cap, scale)
    err = _honest(_errors(cov, scale), half_diff)
    if split:
        return _not_applied("offset differs between short and long wavelengths", n, snr,
                            best, err)
    if cov is None or max(err) > MAX_ERR_PX * pix:
        return _not_applied("offset poorly constrained", n, snr, best, err)
    if reason := _neighbour_reason(neighbours, target_sky, best):
        return _not_applied(reason, n, snr, best, err)
    return Recentre(float(best[0]), float(best[1]), float(err[0]), float(err[1]), True, "",
                    n, snr)
