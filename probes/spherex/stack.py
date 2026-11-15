"""Stacking helpers: resample stamps onto a common north-up TAN grid, forced photometry.

Frames are rotated differently (PC matrix per pointing), so raw stamps are never added.
Each frame is resampled onto a grid centred on a chosen sky position (e.g. the target's
PM-predicted position for that frame), then combined with inverse-variance weights.
"""
from __future__ import annotations

import numpy as np
from astropy.wcs import WCS

from phot import MJYSR_TO_UJY, bilinear, frame_wcs, good_mask, photometry

SCALE_DEG = 6.15 / 3600.0


def grid_wcs(ra: float, dec: float, n: int) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-SCALE_DEG, SCALE_DEG]
    return w


def resample(d: dict, ra: float, dec: float, n: int = 21) -> tuple[np.ndarray, np.ndarray]:
    """Zodi- and annulus-background-subtracted stamp on an n x n north-up grid at (ra, dec).

    Returns (image MJy/sr, variance); bad pixels become NaN (spread by bilinear weights).
    """
    bkg = photometry(d)["bkg"]
    img = np.where(good_mask(d), d["image"] - d["zodi"] - (bkg if np.isfinite(bkg) else 0), np.nan)
    var = np.where(good_mask(d), d["variance"], np.nan)
    gw = grid_wcs(ra, dec, n)
    yy, xx = np.mgrid[0:n, 0:n]
    wra, wdec = gw.pixel_to_world_values(xx, yy)
    fx, fy = frame_wcs(d).world_to_pixel_values(wra, wdec)
    sx, sy = fx - d["x0"], fy - d["y0"]
    return bilinear(img, sy, sx), bilinear(var, sy, sx)


def combine(stack: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inverse-variance weighted mean; returns (mean, variance of mean, n frames per pixel)."""
    im = np.array([s[0] for s in stack])
    var = np.array([s[1] for s in stack])
    w = np.where(np.isfinite(im) & np.isfinite(var) & (var > 0), 1.0 / var, 0.0)
    im0 = np.where(w > 0, im, 0.0)
    ws = w.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (w * im0).sum(0) / ws, 1.0 / ws, (w > 0).sum(0)


def forced(d: dict, dx: float = 0.0, dy: float = 0.0) -> dict:
    """PSF-fit flux at the predicted position shifted by (dx, dy) frame pixels."""
    e = dict(d)
    e["xpix"] = float(d["xpix"]) + dx
    e["ypix"] = float(d["ypix"]) + dy
    return photometry(e)


def wmean(vals: np.ndarray, errs: np.ndarray) -> tuple[float, float]:
    ok = np.isfinite(vals) & np.isfinite(errs) & (errs > 0)
    if not ok.any():
        return np.nan, np.nan
    w = 1.0 / errs[ok] ** 2
    return float(np.sum(w * vals[ok]) / w.sum()), float(1.0 / np.sqrt(w.sum()))


OFFSETS = [(dx, dy) for dx in (-8, 0, 8) for dy in (-8, 0, 8) if (dx, dy) != (0, 0)]


def forced_stack(ds: list[dict]) -> dict:
    """Weighted mean flux at the target and at 8 empty offset positions (uJy).

    S/N is reported two ways: from propagated VARIANCE, and from the robust scatter
    (1.48 x median |flux|) of the 8 empty-position stacks (usually more honest).
    """
    tgt = [photometry(d) for d in ds]
    f, e = wmean(np.array([t["flux"] for t in tgt]), np.array([t["err"] for t in tgt]))
    empties = []
    for dx, dy in OFFSETS:
        rr = [forced(d, dx, dy) for d in ds]
        empties.append(wmean(np.array([r["flux"] for r in rr]), np.array([r["err"] for r in rr]))[0])
    emp = np.array(empties)
    # robust: an offset position sometimes lands on a field star
    sig_emp = float(1.4826 * np.nanmedian(np.abs(emp)))
    return dict(n=int(np.isfinite([t["flux"] for t in tgt]).sum()), flux=f, err=e,
                snr_var=f / e if e else np.nan, sig_empty=sig_emp,
                snr_empty=f / sig_emp if sig_emp else np.nan, empties=emp)


__all__ = ["resample", "combine", "forced_stack", "grid_wcs", "MJYSR_TO_UJY"]
