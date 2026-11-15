"""Manifest `measured_motion` from `trackfit`, for a view whose frames gave no motion.

Used by `build` only when the frame-by-frame centroids did not yield a motion (the target is
under S/N 5 in every visit, or every detection is blended). All W2 visits are fitted at once
(`trackfit.fit`); the catalogued CatWISE neighbours that are in the model are those no more
than `fitblend.BRIGHTNESS_MAG` fainter than the target, within reach of its track, at their
catalogue positions for the mean epoch. A known parallax is put in as a fixed displacement;
an unknown one is left out (it alternates sign between the six-monthly visits, so it adds
scatter, not motion).

No fit is made when the target's track passes within BRIGHT_SEP_ARCSEC of a catalogued source
BRIGHT_MAG or more brighter: on empty sky there the fit returns motions. An independent audit
found 3 of 86 empty places 8-10" from W2 7.5-9.2 stars measured at S/N 5.2-6.7; our own check
around a W2 9.9 star, with a W2 14.7 target assumed (4.8 mag fainter), gave 4 of 8 at 6", 2
of 9 at 8", 1 of 8 at 10" and 0 of 25 at 12-20". So the distance is 12", and the magnitude
limit of 4 is below the smallest difference that produced one (nothing between 2 and 4.8 mag
was tried).

The motion is reported with "method": "all_frames", "n_frames" and "n_detections": 0: no
frame holds a detection of the target. Written with Claude Code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from pxs import centroid, trackfit
from pxs.astrometry import DAYS_PER_YEAR, decimal_year, parallax_factors, propagate
from pxs.blend import is_catwise_piece
from pxs.fitblend import BRIGHTNESS_MAG, _src_at
from pxs.grid import Grid, Stack
from pxs.target import Target

BAND = "W2"
METHOD = "all_frames"
BRIGHT_MAG = 4.0  # module docstring
BRIGHT_SEP_ARCSEC = 12.0
NOTE = ("No single image shows the target clearly enough to measure its position, so its "
        "motion was measured by fitting all {n} W2 images at once.")


def _near_bright_star(t: Target, catwise: Sequence[dict], grid: Grid, years: np.ndarray,
                      seed: tuple[float, float], v: tuple[float, float]) -> bool:
    """True when a CatWISE source at least BRIGHT_MAG brighter than the target lies within
    BRIGHT_SEP_ARCSEC of the target's predicted place in any frame."""
    if t.w2_mag is None:
        return False
    tau = years - years.mean()
    xs, ys = seed[0] + v[0] * tau, seed[1] + v[1] * tau
    limit = BRIGHT_SEP_ARCSEC / grid.pixscale_arcsec
    for s in catwise:
        if s.get("w2_mag") is None or s["w2_mag"] > t.w2_mag - BRIGHT_MAG:
            continue
        x, y = (float(q) for q in grid.sky_to_px(*_src_at(s, float(years.mean()))))
        if float(np.min(np.hypot(xs - x, ys - y))) <= limit:
            return True
    return False


def _neighbours(t: Target, catwise: Sequence[dict], grid: Grid, year: float,
                centre: tuple[float, float], reach_px: float) -> list[tuple[float, float]]:
    """Pixel positions at `year` of the CatWISE sources to model beside the target."""
    if t.w2_mag is None:
        return []
    out = []
    for s in catwise:
        if s.get("w2_mag") is None or s["w2_mag"] > t.w2_mag + BRIGHTNESS_MAG \
                or is_catwise_piece(t, s):
            continue
        x, y = (float(v) for v in grid.sky_to_px(*_src_at(s, year)))
        if math.hypot(x - centre[0], y - centre[1]) <= reach_px:
            out.append((x, y))
    return out


def _parallax_px(stacks: Sequence[Stack], ra: float, dec: float, parallax_mas: float | None,
                 pixscale: float) -> np.ndarray:
    """(n, 2) pixel displacement of the target by its parallax in each frame (x west, y south)."""
    if not parallax_mas:
        return np.zeros((len(stacks), 2))
    f_ra, f_dec = parallax_factors([st.mjd for st in stacks], ra, dec)
    scale = parallax_mas / 1000.0 / pixscale
    return np.column_stack([-f_ra * scale, -f_dec * scale])


def _motion(r: trackfit.TrackFit, pixscale: float, baseline_years: float,
            parallax_mas: float | None) -> dict:
    k = pixscale * 1000.0  # px/yr to mas/yr
    e_ra, e_dec = r.err_v[0] * k, r.err_v[1] * k
    return {
        "pmra_masyr": round(-r.vx * k, 2), "pmdec_masyr": round(-r.vy * k, 2),
        "err_masyr": round(max(e_ra, e_dec), 2),
        "err_pmra_masyr": round(e_ra, 2), "err_pmdec_masyr": round(e_dec, 2),
        "baseline_years": round(baseline_years, 2),
        "n_detections": 0, "n_frames": r.n_frames, "n_rejected": 0, "rejected_reason": None,
        "parallax_model": "fixed" if parallax_mas else "none",
        "parallax_mas": float(parallax_mas) if parallax_mas else None,
        "reduced_chi2": round(r.reduced_chi2, 2),
        "method": METHOD,
    }


def measure(target: Target, grid: Grid, stacks: Sequence[tuple[str, Stack]],
            catwise: Sequence[dict], parallax_mas: float | None = None) -> dict | None:
    """Motion from all W2 frames fitted at once, in the shape of `astrometry.fit_motion`
    plus "method": "all_frames" and "n_frames"; None when it cannot be measured
    (`trackfit.fit`) or the track passes a much brighter star (`_near_bright_star`)."""
    use = [st for band, st in stacks if st.mission == "WISE" and band == BAND
           and np.isfinite(st.image).any()]
    if not target.has_pm or len(use) < trackfit.MIN_FRAMES:
        return None
    pix = grid.pixscale_arcsec
    prep = [centroid._prepare(st, pix) for st in use]
    years = np.array([float(decimal_year(st.mjd)) for st in use])
    ra, dec = propagate(target.ra, target.dec, target.epoch, target.pmra_masyr,
                        target.pmdec_masyr, float(years.mean()))
    seed = tuple(float(v) for v in grid.sky_to_px(ra, dec))
    v = (-target.pmra_masyr / 1000.0 / pix, -target.pmdec_masyr / 1000.0 / pix)
    if _near_bright_star(target, catwise, grid, years, seed, v):
        return None
    frames = trackfit.Frames(
        resid=np.array([f.resid for f in prep]), usable=np.array([f.usable for f in prep]),
        noise=np.array([f.noise for f in prep]), years=years,
        shift_px=_parallax_px(use, ra, dec, parallax_mas, pix))
    half = centroid._fit_half_width_px(prep[0].sigma_px)
    reach = half + prep[0].fwhm_px + 0.5 * math.hypot(*v) * float(np.ptp(years))
    static = _neighbours(target, catwise, grid, float(years.mean()), seed, reach)
    r = trackfit.fit(frames, prep[0].sigma_px, seed, v, static, half,
                     inflate=max(1.0, use[0].native_pixscale_arcsec / pix),
                     snr_min=centroid.SNR_MIN)
    if r is None:
        return None
    baseline = float(np.ptp([st.mjd for st in use])) / DAYS_PER_YEAR
    return _motion(r, pix, baseline, parallax_mas)


def fill(manifest: dict, target: Target, grid: Grid, stacks: Sequence[tuple[str, Stack]],
         catwise: Sequence[dict] | None) -> dict:
    """The manifest with `measured_motion` from all W2 frames (and a note in `warnings`) when
    the frame-by-frame fit gave none. Returned unchanged when it has a motion, when the
    CatWISE query failed (`catwise` None: the neighbours to model are unknown), or when the
    all-frames fit is refused."""
    if manifest.get("measured_motion") is not None or catwise is None:
        return manifest
    motion = measure(target, grid, stacks, catwise, target.parallax_mas)
    if motion is None:
        return manifest
    text = NOTE.format(n=motion["n_frames"])
    return {**manifest, "measured_motion": motion, "warnings": [*manifest["warnings"], text]}
