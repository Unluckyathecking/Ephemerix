"""Measured position of the target in a Stack, independent of where it was predicted to be.

The prediction only decides where to look: a disc of `search_radius_arcsec` around it, sized
from the mission's PSF and the uncertainty of the prediction. Inside the disc the frame is
matched-filtered with a Gaussian of the PSF size and every local maximum above `snr_min`
(against the noise of the filtered frame) is a candidate, as is every saturated core
(`render.saturated_cores`). The candidate nearest the prediction is chosen and measured
starting from that CANDIDATE, never from the prediction:

- an unsaturated source: 2-D Gaussian fit; if the fit wanders more than one FWHM from the
  peak the detection is dropped rather than clamped;
- a saturated core: the centre of point symmetry of the unsaturated wings (`_wing_centre`),
  with the core masked. The WISE and SPHEREx PSFs, diffraction spikes included, are close to
  point-symmetric, and this needs no PSF model. The core's own outline is not used: in late
  NEOWISE visits it is ragged and off-centre by up to 4 arcsec.

Known field stars (`avoid_px`, Gaia sources other than the target, at the frame epoch) do two
jobs. If the chosen peak is closer to one of them than to the prediction, the target counts
as not detected. And the isolated ones that are detected well are fitted the same way as the
target to measure the frame's registration against Gaia (`_registration`); in the bands listed in REG_CORRECTED,
with at least REG_MIN_STARS of them, the median offset is removed from the target position
and noted.

Pixel coordinates use pixel edges (docs/api.md): array element [i, j] has its centre at
(x, y) = (j + 0.5, i + 0.5). Errors are 1 sigma in arcsec: the measurement error (formal fit
error inflated for resampled pixels, floored at ERR_FLOOR_NATIVE_PX; for a saturated core
SATURATED_ERR_NATIVE_PX) in quadrature with the registration error (the correction's own
error plus REG_RESIDUAL_ARCSEC when corrected, else REG_FLOOR_ARCSEC for the mission/band).
The prediction ignores parallax; the motion fit (`astrometry.fit_motion`) models it.
The floors are measured on real stacks.

A neighbour close enough to put light into the target's fitting box is fitted at the same
time as the target (`pairfit`, WISE frames only): the other peaks of the frame near the
target, and the catalogued sources passed as `neighbours_px`, which the smoothed map can
merge with the target.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
from scipy import ndimage, optimize
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.optimize import curve_fit

from pxs import pairfit
from pxs.grid import Stack
from pxs.render import frame_levels, saturated_cores

log = logging.getLogger(__name__)

PSF_PER_NATIVE_PIXEL = 2.2  # fallback FWHM in native pixels for an unknown mission
# FWHM of the stacked PSF on the 1"/px grid, median Gaussian fit to Gaia field stars in the
# 0855, Eps Ind B, 2MASS 0415 and Barnard stacks (W1 363 stars, W2 165, SPHEREx 16-36 per
# window). SPHEREx: 9.0" at 0.75-2.42 um, 10.0" at 2.42-5.0 um.
WISE_FWHM_ARCSEC = {"W1": 6.7, "W2": 7.3}
SPHEREX_FWHM_ARCSEC = ((2.42, 9.0), (math.inf, 10.0))  # (upper wavelength um, FWHM)
SNR_MIN = 5.0
# A peak is a pixel no lower than any other in the PEAK_BOX_PX square around it. The S/N map
# is smoothed with the PSF, so a single source has one maximum. A box one FWHM wide each way
# (17 px in W2) hid a faint target 12" from a brighter star: the star's flank 8-9 px away
# outranked the target's own peak (CWISE J2112-0529, W2 2010, S/N 5.9).
PEAK_BOX_PX = 5
FWHM_TO_SIGMA = 1.0 / 2.3548
# Search disc: SEARCH_FWHM PSF widths plus SEARCH_SIGMA sigma of the predicted position,
# capped at MAX_SEARCH_FWHM widths (W2 44", SPHEREx 4.4-5 um 60").
SEARCH_FWHM = 2.0
SEARCH_SIGMA = 2.0
PM_FRACTION = 0.03  # fractional proper-motion uncertainty (CatWISE motions of bright movers)
PM_FLOOR_MASYR = 30.0  # plus this much in quadrature (CatWISE errors for faint sources)
UNKNOWN_PM_ARCSEC_PER_YR = 1.0  # assumed motion when none is known
MAX_SEARCH_FWHM = 6.0
# Floor on the formal 1-sigma error, in native pixels (resampling and PSF-model limits):
# 0.055" WISE, 0.12" SPHEREx. Registration is added on top (below).
ERR_FLOOR_NATIVE_PX = 0.02
# Saturated core measured from the wings: Barnard's Star W2, 25 visits, scatter about its
# parallax-corrected Gaia track after registration.
SATURATED_ERR_NATIVE_PX = 0.05
CORE_GROW_PX = 2  # pixels around a saturated core that are not trusted either
# Peaks within the core radius plus this many PSF widths of a saturated core are its wings
# and diffraction spikes, not separate sources.
HALO_FWHM = 2.0
WING_WIDTH_FWHM = 1.5  # annulus used by the symmetry fit, outside the core
WING_MAX_SHIFT_FWHM = 0.5  # the symmetry centre may move this far from the core's centre
# Registration against Gaia field stars.
REG_MIN_STARS = 3
REG_ISOLATION_ARCSEC = 12.0
REG_SNR_MIN = 10.0
# Per-frame registration error per axis when no correction is made, from field stars against
# Gaia on four fields and from the targets' own scatter about their parallax-corrected tracks.
# W1 frames sit up to 0.6" off in alternate visits (scan direction), well measured by field
# stars, so W1 is corrected per frame; in W2 the correction added more noise than it removed
# (target scatter 0.06-0.11" uncorrected, 0.11-0.13" corrected), and SPHEREx has 1-2 usable
# stars per frame at 4.4-5 um, so neither is corrected.
REG_FLOOR_ARCSEC = {("WISE", "W1"): 0.40, ("WISE", "W2"): 0.10, ("SPHEREx", None): 0.25}
REG_CORRECTED = {("WISE", "W1")}
REG_RESIDUAL_ARCSEC = 0.08  # W1 scatter left after the per-frame correction


@dataclass(frozen=True)
class Centroid:
    """A measured position: edge-convention pixels, 1-sigma error in arcsec, peak S/N.

    method: "psf" (Gaussian fit) or "wings" (saturated core, symmetry of the wings).
    registration_px: the (dx, dy) grid-pixel offset of Gaia field stars that was removed,
    with n_reference_stars stars; (0, 0) and 0 when no correction was made.
    """

    x: float
    y: float
    err_arcsec: float
    snr: float
    warnings: tuple[str, ...] = ()
    method: str = "psf"
    registration_px: tuple[float, float] = (0.0, 0.0)
    n_reference_stars: int = 0


@dataclass(frozen=True)
class _Frame:
    """Per-frame working arrays shared by the target and reference-star fits."""

    resid: np.ndarray  # background-subtracted image, 0 where not usable
    usable: np.ndarray  # finite and not in or next to a saturated core
    snr: np.ndarray  # matched-filter S/N map
    cores: np.ndarray  # saturated cores (not grown)
    noise: float
    fwhm_px: float
    sigma_px: float


def psf_fwhm_arcsec(stack: Stack) -> float:
    """FWHM of the stacked PSF (arcsec) for the stack's mission and band."""
    if stack.mission == "WISE" and stack.band in WISE_FWHM_ARCSEC:
        return WISE_FWHM_ARCSEC[stack.band]
    if stack.mission == "SPHEREx":
        wl = max(stack.wavelength_um)
        return next(f for top, f in SPHEREX_FWHM_ARCSEC if wl <= top)
    return PSF_PER_NATIVE_PIXEL * stack.native_pixscale_arcsec


def search_radius_arcsec(fwhm_arcsec: float, pm_total_masyr: float | None, dt_years: float,
                         parallax_mas: float | None = None) -> float:
    """Search disc radius (arcsec): SEARCH_FWHM PSF widths plus SEARCH_SIGMA sigma of the
    predicted position, capped at MAX_SEARCH_FWHM widths.

    The prediction's sigma is the proper-motion error times |dt| since the catalogue epoch,
    the error being PM_FRACTION of the motion and PM_FLOOR_MASYR in quadrature, or
    UNKNOWN_PM_ARCSEC_PER_YR when the motion is unknown (None); plus the parallax amplitude
    when given, because the prediction ignores parallax.
    """
    if pm_total_masyr is None:
        pm_err = UNKNOWN_PM_ARCSEC_PER_YR * 1000.0
    else:
        pm_err = math.hypot(PM_FRACTION * pm_total_masyr, PM_FLOOR_MASYR)
    sigma = (pm_err * abs(dt_years) + abs(parallax_mas or 0.0)) / 1000.0
    return min(SEARCH_FWHM * fwhm_arcsec + SEARCH_SIGMA * sigma, MAX_SEARCH_FWHM * fwhm_arcsec)


def _reg_floor(stack: Stack) -> float:
    key = (stack.mission, stack.band if stack.mission == "WISE" else None)
    return REG_FLOOR_ARCSEC.get(key, REG_FLOOR_ARCSEC[("WISE", "W2")])


def _gauss(xy, amp, x0, y0, sigma, offset):
    x, y = xy
    return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma**2)) + offset


def _prepare(stack: Stack, pixscale_arcsec: float) -> _Frame:
    cores = saturated_cores(stack)
    bad = ndimage.binary_dilation(cores, iterations=CORE_GROW_PX) if cores.any() else cores
    usable = np.isfinite(stack.image) & ~bad
    lv = frame_levels(np.where(usable, stack.image, np.nan))
    resid = np.where(usable, stack.image - lv.background, 0.0)
    fwhm_px = psf_fwhm_arcsec(stack) / pixscale_arcsec
    sigma_px = fwhm_px * FWHM_TO_SIGMA
    snr = _snr_map(resid, usable, sigma_px)
    return _Frame(resid, usable, snr, cores, lv.noise, fwhm_px, sigma_px)


def _snr_map(resid: np.ndarray, usable: np.ndarray, sigma_px: float) -> np.ndarray:
    """Matched-filter S/N: the residual smoothed with the PSF over the smoothed map's noise."""
    smooth = gaussian_filter(resid, sigma_px, mode="constant")
    s_noise = frame_levels(np.where(usable, smooth, np.nan)).noise
    return np.where(usable, smooth / s_noise, -np.inf)


def _without(fr: _Frame, fit) -> _Frame:
    """The frame with a fitted Gaussian source (`_fit` result) subtracted, S/N map remade."""
    yy, xx = np.mgrid[0:fr.resid.shape[0], 0:fr.resid.shape[1]] + 0.5
    model = _gauss((xx, yy), fit[4], fit[0], fit[1], fit[5], 0.0)
    resid = np.where(fr.usable, fr.resid - model, 0.0)
    return replace(fr, resid=resid, snr=_snr_map(resid, fr.usable, fr.sigma_px))


def _core_candidates(fr: _Frame, predicted, radius_px) -> list[tuple[float, float, float]]:
    """Saturated cores whose centre lies in the disc, as (x, y, snr=inf)."""
    labels, n = ndimage.label(fr.cores)
    if n == 0:
        return []
    centres = ndimage.center_of_mass(fr.cores, labels, range(1, n + 1))
    out = [(c[1] + 0.5, c[0] + 0.5, math.inf) for c in centres]
    return [c for c in out if math.hypot(c[0] - predicted[0], c[1] - predicted[1]) <= radius_px]


def _peaks(fr: _Frame, predicted, radius_px, snr_min):
    """Significant local maxima and saturated cores inside the disc, as (x, y, snr), nearest
    the prediction first. Peaks in the halo of a core are the core, not separate sources."""
    is_max = ((fr.snr == maximum_filter(fr.snr, size=PEAK_BOX_PX, mode="nearest"))
              & (fr.snr >= snr_min))
    ii, jj = np.nonzero(is_max)
    cores = _core_candidates(fr, predicted, radius_px)
    rim = np.zeros(ii.size, bool)
    if fr.cores.any():
        r_core = math.sqrt(np.bincount(ndimage.label(fr.cores)[0].ravel())[1:].max() / math.pi)
        halo = r_core + CORE_GROW_PX + HALO_FWHM * fr.fwhm_px
        rim = ndimage.distance_transform_edt(~fr.cores)[ii, jj] <= halo
    pts = [(j + 0.5, i + 0.5, float(fr.snr[i, j])) for i, j, r in zip(ii, jj, rim) if not r]
    pts = [p for p in pts if math.hypot(p[0] - predicted[0], p[1] - predicted[1]) <= radius_px]
    return sorted(pts + cores, key=lambda p: math.hypot(p[0] - predicted[0], p[1] - predicted[1]))


def _fit_half_width_px(sigma_px: float) -> int:
    return int(np.ceil(3.0 * sigma_px)) + 1


def fit_radius_arcsec(fwhm_arcsec: float, pixscale_arcsec: float) -> float:
    """Half-width (arcsec) of the box of pixels the Gaussian fit in `_fit` uses."""
    return _fit_half_width_px(fwhm_arcsec * FWHM_TO_SIGMA / pixscale_arcsec) * pixscale_arcsec


def _fit(fr: _Frame, peak) -> tuple[float, float, float, float, float, float] | None:
    """2-D Gaussian fit around the peak. Returns (x, y, sx, sy, amplitude, sigma), positions
    and sigma in edge pixels, or None."""
    r = _fit_half_width_px(fr.sigma_px)
    i0, j0 = int(peak[1]), int(peak[0])
    ny, nx = fr.resid.shape
    sl = (slice(max(i0 - r, 0), min(i0 + r + 1, ny)), slice(max(j0 - r, 0), min(j0 + r + 1, nx)))
    ii, jj = np.mgrid[sl]  # clipped at both ends, so it matches usable[sl] near any edge
    ok = fr.usable[sl]
    if ok.sum() < 8:
        return None
    xy = (jj[ok] + 0.5, ii[ok] + 0.5)
    z = fr.resid[sl][ok]
    p0 = (max(float(z.max()), fr.noise), peak[0], peak[1], fr.sigma_px, 0.0)
    try:
        p, cov = curve_fit(_gauss, xy, z, p0=p0, sigma=np.full(z.shape, fr.noise),
                           absolute_sigma=True, maxfev=4000)
    except (RuntimeError, ValueError) as exc:
        log.info("centroid fit failed: %s", exc)
        return None
    sx, sy = np.sqrt(np.abs(np.diag(cov)[1:3]))
    if not np.all(np.isfinite([p[1], p[2], sx, sy])) or p[0] <= 0:
        return None
    if math.hypot(p[1] - peak[0], p[2] - peak[1]) > fr.fwhm_px:
        return None
    return float(p[1]), float(p[2]), float(sx), float(sy), float(p[0]), abs(float(p[3]))


def _symmetry_cost(fr: _Frame, xs, ys, vals):
    """Mean squared difference between the wing pixels and their point reflections."""
    data, weight = fr.resid, fr.usable.astype(float)

    def cost(c) -> float:
        coords = [2 * c[1] - ys - 0.5, 2 * c[0] - xs - 0.5]
        vr = ndimage.map_coordinates(data, coords, order=1, mode="constant")
        wr = ndimage.map_coordinates(weight, coords, order=1, mode="constant")
        ok = wr > 0.99
        return float(np.mean((vals[ok] - vr[ok]) ** 2)) if ok.sum() > 20 else math.inf

    return cost


def _wing_centre(fr: _Frame, core_xy) -> tuple[float, float] | None:
    """Centre of point symmetry of the unsaturated wings around a saturated core (edge px).

    Seeded on a coarse grid around the core's centre, refined with Nelder-Mead; None when
    the best centre is more than WING_MAX_SHIFT_FWHM PSF widths from the seed region."""
    labels, _ = ndimage.label(fr.cores)
    k = labels[min(int(core_xy[1]), labels.shape[0] - 1), min(int(core_xy[0]), labels.shape[1] - 1)]
    r_core = math.sqrt((labels == k).sum() / math.pi) if k else 0.0
    yy, xx = np.mgrid[0:fr.resid.shape[0], 0:fr.resid.shape[1]] + 0.5
    r = np.hypot(xx - core_xy[0], yy - core_xy[1])
    ann = fr.usable & (r <= r_core + CORE_GROW_PX + WING_WIDTH_FWHM * fr.fwhm_px)
    if ann.sum() < 50:
        return None
    cost = _symmetry_cost(fr, xx[ann], yy[ann], fr.resid[ann])
    reach = WING_MAX_SHIFT_FWHM * fr.fwhm_px
    grid = np.arange(-reach, reach + 1e-9, 0.5)
    seed = min(((core_xy[0] + dx, core_xy[1] + dy) for dx in grid for dy in grid), key=cost)
    res = optimize.minimize(cost, seed, method="Nelder-Mead",
                            options={"xatol": 1e-3, "fatol": 1e-9, "maxiter": 400})
    x, y = (float(v) for v in res.x)
    if not np.isfinite(res.fun) or math.hypot(x - core_xy[0], y - core_xy[1]) > 1.5 * reach:
        return None
    return x, y


def _isolated(avoid: np.ndarray, sep_px: float) -> np.ndarray:
    d = np.hypot(avoid[:, None, 0] - avoid[None, :, 0], avoid[:, None, 1] - avoid[None, :, 1])
    return (d < sep_px).sum(axis=1) == 1


def _registration(fr: _Frame, avoid, target_xy, pixscale) -> tuple[np.ndarray, int, float]:
    """Median (dx, dy) of measured minus Gaia positions of isolated field stars (grid px),
    their number, and the 1-sigma error of the median per axis (arcsec)."""
    if not avoid:
        return np.zeros(2), 0, 0.0
    a = np.asarray(avoid, float).reshape(-1, 2)
    ny, nx = fr.resid.shape
    margin = 3.0 * fr.sigma_px + 2
    keep = (_isolated(a, REG_ISOLATION_ARCSEC / pixscale)
            & (np.hypot(a[:, 0] - target_xy[0], a[:, 1] - target_xy[1]) > 3 * fr.fwhm_px)
            & (a[:, 0] > margin) & (a[:, 0] < nx - margin)
            & (a[:, 1] > margin) & (a[:, 1] < ny - margin))
    offs = []
    for x, y in a[keep]:
        i, j = int(y), int(x)
        if not fr.usable[i, j] or fr.snr[i, j] < REG_SNR_MIN:
            continue
        fit = _fit(fr, (x, y))
        if fit is not None and math.hypot(fit[0] - x, fit[1] - y) < 0.5 * fr.fwhm_px:
            offs.append((fit[0] - x, fit[1] - y))
    if len(offs) < REG_MIN_STARS:
        return np.zeros(2), len(offs), 0.0
    o = np.array(offs)
    spread = 1.4826 * np.median(np.abs(o - np.median(o, axis=0)), axis=0)
    err = float(np.max(1.2533 * spread / math.sqrt(len(o)))) * pixscale
    return np.median(o, axis=0), len(o), err


ON_KNOWN_STAR = "nearest source is a catalogued star, not the target"
STAR_REMOVED = "a catalogued star next to the target was fitted and removed first"
REMOVE_MAX_SNR = 30.0  # brighter stars leave residuals a Gaussian model cannot remove
SATURATED_NOTE = "saturated core: position measured from the unsaturated wings"
JOINT = "position fitted together with a neighbouring source"
JOINT_MISSIONS = frozenset({"WISE"})  # pairfit is checked on real WISE frames only
WINGS_FAILED = "saturated core: the wings were too asymmetric to measure a position"


def _core_covers(fr: _Frame, xy) -> bool:
    """True when the point lies within CORE_GROW_PX + one FWHM of a saturated core."""
    i, j = int(xy[1]), int(xy[0])
    if not (0 <= i < fr.cores.shape[0] and 0 <= j < fr.cores.shape[1]):
        return False
    reach = int(np.ceil(CORE_GROW_PX + fr.fwhm_px))
    sl = (slice(max(i - reach, 0), i + reach + 1), slice(max(j - reach, 0), j + reach + 1))
    return bool(fr.cores[sl].any())


def _on_known(peak, predicted, avoid) -> bool:
    """True when the peak is closer to a known field star than to the prediction."""
    if not avoid:
        return False
    a = np.asarray(avoid, float).reshape(-1, 2)
    to_pred = np.hypot(peak[0] - predicted[0], peak[1] - predicted[1])
    return bool(np.min(np.hypot(a[:, 0] - peak[0], a[:, 1] - peak[1])) < to_pred)


def _ambiguity(peaks, predicted, fwhm_px) -> tuple[str, ...]:
    near = [p for p in peaks if np.hypot(p[0] - predicted[0], p[1] - predicted[1]) <= 2 * fwhm_px]
    if len(near) > 1:
        return ((f"{len(near)} sources within two PSF widths of the predicted position; "
                "took the nearest"),)
    return ()


def _retry_without_star(fr: _Frame, peaks, stack: Stack, pixscale, predicted, radius_px,
                        snr_min, avoid):
    """(frame, peaks, measurement) after fitting and subtracting the catalogued star nearest
    the prediction, or None. For a faint target that the PSF-smoothed map merges with a
    brighter star 10-12" away (CWISE J2112-0529 in stacked W2 visits): either the nearest
    peak is then the star, or the target's own fit is pulled onto the star and dropped.
    The new candidate still comes from the data, never from the prediction. Only a star of
    S/N up to REMOVE_MAX_SNR is removed, and the new candidate must lie more than one FWHM
    from it: a Gaussian does not fit a bright star's real PSF, and the residual made false
    detections 4-8" from the prediction next to a G = 11.6 star (CWISE J2021+1524).
    The joint fit with neighbours is not used on the subtracted frame: it was checked on
    untouched frames only."""
    star = next((p for p in peaks if not math.isinf(p[2]) and _on_known(p, predicted, avoid)),
                None)
    fit = None if star is None or star[2] > REMOVE_MAX_SNR else _fit(fr, star)
    if fit is None:
        return None
    clean = _without(fr, fit)
    found = _peaks(clean, predicted, radius_px, snr_min)
    if (not found or _on_known(found[0], predicted, avoid)
            or math.hypot(found[0][0] - fit[0], found[0][1] - fit[1]) <= fr.fwhm_px):
        return None
    m = _measure_peak(clean, found[0], stack, pixscale, joint=False)
    return None if m is None else (clean, found, m)


def _joint_fit(fr: _Frame, peak, known_px, snr_min) -> pairfit.PairFit | None:
    """`pairfit.fit` of the target peak with its neighbours: the frame's other peaks within
    reach, and the catalogued positions `known_px` that are not one of those peaks. None
    when there is no neighbour, one of them is brighter than pairfit allows, or the joint
    fit is refused."""
    half = _fit_half_width_px(fr.sigma_px)
    reach = half + pairfit.REACH_FWHM * fr.fwhm_px

    def near(p) -> bool:
        return 0.5 < math.hypot(p[0] - peak[0], p[1] - peak[1]) <= reach

    others = [p for p in _peaks(fr, peak, reach, snr_min) if near(p)]
    if any(p[2] > pairfit.MAX_FLUX_RATIO * peak[2] for p in others):
        return None  # a saturated or clearly brighter neighbour: not what pairfit is checked on
    seen = [(p[0], p[1]) for p in others]
    known = [(k[0], k[1]) for k in known_px if near(k)
             and all(math.hypot(k[0] - s[0], k[1] - s[1]) > 0.5 * fr.fwhm_px for s in seen)]
    return pairfit.fit(fr.resid, fr.usable, fr.noise, fr.sigma_px, half, (peak[0], peak[1]),
                       seen + known, fr.fwhm_px, pairfit.MIN_SEP_FWHM * fr.fwhm_px)


def _measure_peak(fr: _Frame, peak, stack: Stack, pixscale, known_px=(), snr_min=SNR_MIN,
                  joint=True):
    """(x, y, measurement error arcsec, method, notes) or None for the chosen candidate.
    `joint`: fit close neighbours at the same time (`_joint_fit`) where that applies."""
    corr = max(1.0, stack.native_pixscale_arcsec / pixscale)
    if math.isinf(peak[2]):
        xy = _wing_centre(fr, peak)
        if xy is None:
            return None
        return xy[0], xy[1], SATURATED_ERR_NATIVE_PX * stack.native_pixscale_arcsec, "wings", ()
    pair = (_joint_fit(fr, peak, known_px, snr_min)
            if joint and stack.mission in JOINT_MISSIONS else None)
    if pair is not None:
        fit = (pair.x, pair.y, pair.sx, pair.sy)
        sep = min(math.hypot(n[0] - pair.x, n[1] - pair.y) for n in pair.neighbours) * pixscale
        notes: tuple[str, ...] = (f"{JOINT} {sep:.1f} arcsec away",)
    else:
        fit, notes = _fit(fr, peak), ()
    if fit is None:
        return None
    err = float(np.hypot(fit[2], fit[3]) / np.sqrt(2.0)) * pixscale * corr
    floor = ERR_FLOOR_NATIVE_PX * stack.native_pixscale_arcsec
    return fit[0], fit[1], max(err, floor), "psf", notes


def _register(fr, stack, pixscale, avoid, x, y, err_meas):
    """Apply the Gaia registration to (x, y); returns (x, y, total error, offset, n, notes)."""
    if (stack.mission, stack.band) not in REG_CORRECTED:
        return x, y, math.hypot(err_meas, _reg_floor(stack)), (0.0, 0.0), 0, ()
    off, n, err_corr = _registration(fr, avoid, (x, y), pixscale)
    if n < REG_MIN_STARS:
        return x, y, math.hypot(err_meas, _reg_floor(stack)), (0.0, 0.0), 0, ()
    e, nn = -off[0] * pixscale, -off[1] * pixscale  # grid x grows west, y grows south
    note = (f"registered to {n} Gaia stars: frame offset {e:+.2f}\" E, {nn:+.2f}\" N removed",)
    err = math.sqrt(err_meas**2 + err_corr**2 + REG_RESIDUAL_ARCSEC**2)
    return x - off[0], y - off[1], err, (float(off[0]), float(off[1])), n, note


def detect(
    stack: Stack,
    predicted_px: tuple[float, float],
    pixscale_arcsec: float,
    search_radius: float,
    snr_min: float = SNR_MIN,
    avoid_px: Sequence[tuple[float, float]] = (),
    neighbours_px: Sequence[tuple[float, float]] = (),
) -> tuple[Centroid | None, tuple[str, ...]]:
    """Measure the target near `predicted_px` (edge pixels); `search_radius` in arcsec.

    `avoid_px`: pixel positions at the frame epoch of known field stars that are not the
    target. `neighbours_px`: catalogued sources of similar brightness, fitted together with
    the target when they are close enough (`_joint_fit`). Returns (None, notes) when no candidate inside the disc reaches `snr_min`, when
    the nearest is a known field star (the target is then not detected; the note says so),
    or the measurement fails.
    """
    if not np.isfinite(stack.image).any():
        return None, ()
    fr = _prepare(stack, pixscale_arcsec)
    peaks = _peaks(fr, predicted_px, search_radius / pixscale_arcsec, snr_min)
    if not peaks:
        return None, ()
    # A saturated core covering the prediction is the target even when a catalogued neighbour
    # sits inside it (RW Aur B, 1.4" from A).
    covers = math.isinf(peaks[0][2]) and _core_covers(fr, predicted_px)
    on_star = not covers and _on_known(peaks[0], predicted_px, avoid_px)
    m = None if on_star else _measure_peak(fr, peaks[0], stack, pixscale_arcsec,
                                           neighbours_px, snr_min)
    removed: tuple[str, ...] = ()
    if m is None and not math.isinf(peaks[0][2]):
        retry = _retry_without_star(fr, peaks, stack, pixscale_arcsec, predicted_px,
                                    search_radius / pixscale_arcsec, snr_min, avoid_px)
        if retry is not None:
            (fr, peaks, m), removed = retry, (STAR_REMOVED,)
    if m is None:
        if on_star:
            return None, (ON_KNOWN_STAR,)
        return None, (WINGS_FAILED,) if math.isinf(peaks[0][2]) else ()
    x, y, err, off, n, reg_note = _register(fr, stack, pixscale_arcsec, avoid_px, *m[:3])
    snr = float(fr.snr[min(int(m[1]), fr.snr.shape[0] - 1), min(int(m[0]), fr.snr.shape[1] - 1)])
    notes = (*removed, *_ambiguity(peaks, predicted_px, fr.fwhm_px), *m[4],
             *((SATURATED_NOTE,) if m[3] == "wings" else ()), *reg_note)
    snr = snr if np.isfinite(snr) and snr > 0 else float("inf") if m[3] == "wings" else snr
    return Centroid(x, y, err, min(snr, 1e6), notes, m[3], off, n), ()


def measure(
    stack: Stack,
    predicted_px: tuple[float, float],
    pixscale_arcsec: float,
    search_radius: float,
    snr_min: float = SNR_MIN,
    avoid_px: Sequence[tuple[float, float]] = (),
) -> Centroid | None:
    """`detect` without the notes: the Centroid, or None when the target is not detected."""
    return detect(stack, predicted_px, pixscale_arcsec, search_radius, snr_min, avoid_px)[0]
