"""Sky positions, proper motion and pixel coordinates for the view manifest.

Units: angles in degrees (ICRS) unless a name says otherwise, proper motion in
mas/yr (pmra already includes cos dec), times as decimal Julian years or MJD.

Pixel convention (docs/api.md): gnomonic projection about the grid centre, north
up, east left, origin at the top-left corner of the image, x right, y down, in
pixel units. The grid centre sits at (size_px / 2, size_px / 2).
"""

from __future__ import annotations

import numpy as np

ARCSEC_PER_DEG = 3600.0
MAS_PER_DEG = 3.6e6
DAYS_PER_YEAR = 365.25
_MJD_J2000 = 51544.5


def decimal_year(mjd):
    """Julian epoch (decimal year) for a Modified Julian Date."""
    return 2000.0 + (np.asarray(mjd, dtype=float) - _MJD_J2000) / DAYS_PER_YEAR


def propagate(ra, dec, epoch, pmra_masyr, pmdec_masyr, to_year):
    """Move a position (deg) from `epoch` to `to_year` with linear proper motion (mas/yr).

    pmra_masyr already includes cos(dec); cos(dec) is taken at the starting
    declination. Parallax is ignored. Returns (ra_deg, dec_deg).
    """
    dt = to_year - epoch
    dec_new = dec + pmdec_masyr * dt / MAS_PER_DEG
    ra_new = ra + pmra_masyr * dt / MAS_PER_DEG / np.cos(np.radians(dec))
    return ra_new % 360.0, dec_new


def _tangent_offsets(ra, dec, ra0, dec0):
    """Gnomonic offsets (xi east, eta north) in radians of (ra, dec) about (ra0, dec0) in degrees."""
    a, d = np.radians(ra), np.radians(dec)
    a0, d0 = np.radians(ra0), np.radians(dec0)
    da = a - a0
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(da)
    xi = np.cos(d) * np.sin(da) / cosc
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(da)) / cosc
    return xi, eta


def sky_to_px(ra, dec, center_ra, center_dec, fov_arcsec, size_px):
    """Pixel (x, y) of a sky position on the manifest grid. Inputs in degrees; works on arrays."""
    scale = np.radians(fov_arcsec / ARCSEC_PER_DEG) / size_px  # radians per pixel
    xi, eta = _tangent_offsets(ra, dec, center_ra, center_dec)
    half = size_px / 2.0
    return half - xi / scale, half - eta / scale


def px_to_sky(x, y, center_ra, center_dec, fov_arcsec, size_px):
    """Inverse of sky_to_px: (ra_deg, dec_deg) of pixel (x, y)."""
    scale = np.radians(fov_arcsec / ARCSEC_PER_DEG) / size_px
    half = size_px / 2.0
    xi = (half - np.asarray(x, dtype=float)) * scale
    eta = (half - np.asarray(y, dtype=float)) * scale
    a0, d0 = np.radians(center_ra), np.radians(center_dec)
    rho = np.hypot(xi, eta)
    c = np.arctan(rho)
    safe = np.where(rho == 0, 1.0, rho)
    dec = np.arcsin(np.cos(c) * np.sin(d0) + eta * np.sin(c) * np.cos(d0) / safe)
    ra = a0 + np.arctan2(xi * np.sin(c), rho * np.cos(d0) * np.cos(c) - eta * np.sin(d0) * np.sin(c))
    return np.degrees(ra) % 360.0, np.degrees(dec)


def track(target, center, fov_arcsec, size_px, start_year=2010, end_year=2027):
    """Manifest `track`: predicted pixel position once a year, start_year to end_year inclusive.

    `target` and `center` are the manifest blocks (ra, dec, epoch, pmra_masyr,
    pmdec_masyr; ra, dec). Returns [] when the proper motion or epoch is unknown.
    """
    pmra, pmdec, epoch = (target.get(k) for k in ("pmra_masyr", "pmdec_masyr", "epoch"))
    if pmra is None or pmdec is None or epoch is None:
        return []
    out = []
    for year in range(int(start_year), int(end_year) + 1):
        ra, dec = propagate(target["ra"], target["dec"], epoch, pmra, pmdec, year)
        x, y = sky_to_px(ra, dec, center["ra"], center["dec"], fov_arcsec, size_px)
        out.append({"year": float(year), "px": [round(float(x), 3), round(float(y), 3)]})
    return out


CLIP_SIGMA = 4.0  # an epoch this far from the fitted track (in its own errors) is rejected
MAX_REJECT_FRACTION = 0.15  # never reject more than this share of the epochs (at least 1)
MIN_FREE_PARALLAX = 10  # epochs needed to fit an unknown parallax alongside the motion


def parallax_factors(mjd, ra, dec):
    """Displacement (east, north) per unit parallax at times `mjd` for a star at (ra, dec) deg.

    Uses the Earth's barycentric position (astropy's built-in ephemeris, offline), standard
    factors: d_ra* = p (X sin a - Y cos a), d_dec = p (X cos a sin d + Y sin a sin d - Z cos d)
    with X, Y, Z in au. Multiply by the parallax in mas to get mas. WISE and SPHEREx orbit the
    Earth, so the geocentre is close enough (under 1e-4 au).
    """
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time

    xyz = get_body_barycentric("earth", Time(np.asarray(mjd, dtype=float), format="mjd"))
    x, y, z = (np.asarray(v) for v in xyz.xyz.to_value("au"))
    a, d = np.radians(ra), np.radians(dec)
    f_ra = x * np.sin(a) - y * np.cos(a)
    f_dec = x * np.cos(a) * np.sin(d) + y * np.sin(a) * np.sin(d) - z * np.cos(d)
    return f_ra, f_dec


def _design(t, f_ra, f_dec, free_plx):
    """Joint design matrix for (x0, pmra, y0, pmdec[, parallax]) on stacked [x; y] data."""
    n = t.size
    zero, one = np.zeros(n), np.ones(n)
    cols = [np.r_[one, zero], np.r_[t, zero], np.r_[zero, one], np.r_[zero, t]]
    if free_plx:
        cols.append(np.r_[f_ra, f_dec])
    return np.column_stack(cols)


def _solve(a, b, w):
    """Weighted least squares: parameters, covariance (from the stated errors), chi2."""
    aw = a * np.sqrt(w)[:, None]
    cov = np.linalg.inv(aw.T @ aw)
    p = cov @ (aw.T @ (b * np.sqrt(w)))
    chi2 = float(np.sum(w * (b - a @ p) ** 2))
    return p, cov, chi2


def _fit_robust(a, b, err, n_pts):
    """Fit, then reject the worst epoch while it is over CLIP_SIGMA, up to the cap.
    Returns (params, cov, chi2, kept-epoch mask)."""
    keep = np.ones(n_pts, bool)
    cap = max(1, int(MAX_REJECT_FRACTION * n_pts))
    while True:
        k2 = np.r_[keep, keep]
        p, cov, chi2 = _solve(a[k2], b[k2], 1.0 / err[k2] ** 2)
        r = (b - a @ p) / err
        norm = np.sqrt((r[:n_pts] ** 2 + r[n_pts:] ** 2) / 2.0)
        norm[~keep] = -1.0
        worst = int(np.argmax(norm))
        dof = 2 * keep.sum() - a.shape[1]
        if norm[worst] <= CLIP_SIGMA or (~keep).sum() >= cap or dof <= 2:
            return p, cov, chi2, keep
        keep[worst] = False


def fit_motion(mjds, ras, decs, errs_arcsec, parallax_mas=None):
    """Manifest `measured_motion` from a weighted fit of position against time.

    mjds in days, ras/decs in degrees, errs_arcsec the 1-sigma position error per point,
    parallax_mas the target's parallax if known. Fits tangent-plane offsets in both axes at
    once: linear motion, plus parallax (fixed when given; fitted when unknown and there are
    MIN_FREE_PARALLAX epochs; otherwise left out). Epochs more than CLIP_SIGMA from the fitted
    track are rejected one at a time, at most MAX_REJECT_FRACTION of them; the count is
    reported. Errors per axis come from the stated errors, scaled up by sqrt(reduced chi2)
    when the scatter exceeds them; err_masyr is the larger axis error. Returns None for fewer
    than 2 valid points or a zero time baseline.
    """
    mjd, ra, dec, err = (np.asarray(a, dtype=float) for a in (mjds, ras, decs, errs_arcsec))
    ok = np.isfinite(mjd) & np.isfinite(ra) & np.isfinite(dec) & np.isfinite(err) & (err > 0)
    mjd, ra, dec, err = mjd[ok], ra[ok], dec[ok], err[ok]
    if mjd.size < 2 or np.ptp(mjd) == 0:
        return None
    # Offsets about the first point: a mean of RAs either side of 0 would be about 180 deg.
    xi, eta = _tangent_offsets(ra, dec, ra[0], dec[0])
    x_as, y_as = (np.degrees(v) * ARCSEC_PER_DEG for v in (xi, eta))
    t = (mjd - mjd.mean()) / DAYS_PER_YEAR
    f_ra, f_dec = parallax_factors(mjd, ra[0], dec[0])
    free = parallax_mas is None and mjd.size >= MIN_FREE_PARALLAX
    plx_as = (parallax_mas or 0.0) / 1000.0
    b = np.r_[x_as - plx_as * f_ra, y_as - plx_as * f_dec]
    a = _design(t, f_ra, f_dec, free)
    p, cov, chi2, keep = _fit_robust(a, b, np.r_[err, err], mjd.size)
    dof = 2 * int(keep.sum()) - a.shape[1]
    red = chi2 / dof if dof > 0 else float("nan")
    scale = np.sqrt(max(1.0, red)) if dof > 0 else 1.0
    e = np.sqrt(np.diag(cov)) * scale * 1000.0
    used = mjd[keep]
    return {
        "pmra_masyr": round(float(p[1]) * 1000.0, 2),
        "pmdec_masyr": round(float(p[3]) * 1000.0, 2),
        "err_masyr": round(float(max(e[1], e[3])), 2),
        "err_pmra_masyr": round(float(e[1]), 2),
        "err_pmdec_masyr": round(float(e[3]), 2),
        "baseline_years": round(float(np.ptp(used)) / DAYS_PER_YEAR, 2),
        "n_detections": int(keep.sum()),
        "n_rejected": int((~keep).sum()),
        "rejected_reason": (f"more than {CLIP_SIGMA:g} sigma from the fitted track"
                            if (~keep).any() else None),
        "parallax_model": "fixed" if parallax_mas is not None else "fitted" if free else "none",
        # A fitted parallax is not reported: WISE registration errors that change with scan
        # direction share its six-month cadence, so it is a nuisance parameter here.
        "parallax_mas": None if parallax_mas is None else float(parallax_mas),
        "reduced_chi2": None if not np.isfinite(red) else round(float(red), 2),
    }
