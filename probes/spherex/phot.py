"""Shared helpers for checks 3-6: cached stamp fetch, PSF photometry, resampling.

Stamps are cached as .npz under cache/spherex_stamps/<target>/ so reruns fetch nothing.
"""
from __future__ import annotations

import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

from stamp import BAD_MASK, read_stamp
from targets import coord_at

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
IMG = ROOT / "docs" / "validation" / "img"
PIX_SR = (6.15 / 206264.806) ** 2  # nominal pixel solid angle, sr
MJYSR_TO_UJY = PIX_SR * 1e12        # MJy/sr in one pixel -> microJy
WORKERS = 8


def frames(target: str, collections=("spherex_dr1", "spherex_qr3")) -> list[dict]:
    allf = json.load(open(CACHE / "spherex_frames.json"))[target]
    return sorted((f for f in allf if f["collection"] in collections), key=lambda f: f["mjd"])


def _cache_path(target: str, f: dict) -> Path:
    return CACHE / "spherex_stamps" / target / f"{f['obs_id']}_D{f['detector']}.npz"


def get_stamp(target: str, f: dict, half: int = 15) -> dict | None:
    """Stamp at the PM-propagated position for this frame's epoch (cached)."""
    p = _cache_path(target, f)
    if p.exists():
        d = dict(np.load(p, allow_pickle=False))
        d["cached"] = True
        return d
    c = coord_at(target, f["mjd"])
    t = time.time()
    try:
        s = read_stamp(f["s3_key"], c.ra.deg, c.dec.deg, half=half, psf=True)
    except Exception as e:  # noqa: BLE001 - probe: record and move on
        print(f"  FAIL {f['obs_id']} D{f['detector']}: {e!r}")
        return None
    psf, cw, cb = s.psf or (np.zeros((33, 33)), np.nan, np.nan)
    d = dict(image=s.image, flags=s.flags, variance=s.variance, zodi=s.zodi, psf=psf,
             x0=s.x0, y0=s.y0, xpix=s.xpix, ypix=s.ypix, wave=s.wave_um, band=s.band_um,
             psf_cwave=cw, mjd=s.mjd, det=s.detector, ra=c.ra.deg, dec=c.dec.deg,
             header=s.header.tostring(), nbytes=s.bytes_read, seconds=time.time() - t)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(p, **d)
    d["cached"] = False
    return d


def get_stamps(target: str, fs: list[dict], half: int = 15) -> list[dict]:
    t = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        out = [d for d in ex.map(lambda f: get_stamp(target, f, half), fs) if d is not None]
    new = [d for d in out if not d["cached"]]
    mb = sum(float(d["nbytes"]) for d in new) / 1e6
    print(f"{target}: {len(out)}/{len(fs)} stamps, {len(new)} fetched ({mb:.0f} MB) "
          f"in {time.time() - t:.1f}s with {WORKERS} threads")
    return out


def frame_wcs(d: dict) -> WCS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(fits.Header.fromstring(str(d["header"])))


def psf_model(d: dict) -> np.ndarray:
    """EPSF (33x33, oversampled x5, centred on [16,16]) sampled at stamp pixels."""
    psf = d["psf"]
    ny, nx = d["image"].shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    dx = xx + d["x0"] - d["xpix"]
    dy = yy + d["y0"] - d["ypix"]
    return bilinear(psf, 16 + 5 * dy, 16 + 5 * dx, fill=0.0) * 25.0


def bilinear(a: np.ndarray, y: np.ndarray, x: np.ndarray, fill=np.nan) -> np.ndarray:
    """Bilinear sample of 2-D array `a` at fractional (y, x); NaN-aware via `fill`."""
    ny, nx = a.shape
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    tx, ty = x - x0, y - y0
    ok = (x0 >= 0) & (y0 >= 0) & (x0 < nx - 1) & (y0 < ny - 1)
    x0c, y0c = np.clip(x0, 0, nx - 2), np.clip(y0, 0, ny - 2)
    v = ((1 - tx) * (1 - ty) * a[y0c, x0c] + tx * (1 - ty) * a[y0c, x0c + 1]
         + (1 - tx) * ty * a[y0c + 1, x0c] + tx * ty * a[y0c + 1, x0c + 1])
    return np.where(ok, v, fill)


def good_mask(d: dict, bad_mask: int = BAD_MASK) -> np.ndarray:
    return ((d["flags"] & bad_mask) == 0) & np.isfinite(d["image"]) & np.isfinite(d["variance"])


def photometry(d: dict, r_fit: float = 3.0, r_in: float = 6.0, r_out: float = 10.0) -> dict:
    """Zodi-subtracted PSF-fit flux (uJy) at the predicted position, masking bad pixels.

    Background: sigma-clipped median of the residual (IMAGE-ZODI) in an annulus.
    Flux: weighted linear fit of A*PSF to good pixels within r_fit px.
    Also returns a plain aperture sum (r=2 px) and the masked fraction in the core.
    """
    img = d["image"] - d["zodi"]
    good = good_mask(d)
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx + d["x0"] - d["xpix"], yy + d["y0"] - d["ypix"])
    ann = good & (r >= r_in) & (r < r_out)
    bkg = np.nan
    if ann.sum() > 10:
        v = img[ann]
        med = np.median(v)
        mad = 1.4826 * np.median(np.abs(v - med))
        bkg = float(np.median(v[np.abs(v - med) < 3 * mad])) if mad > 0 else float(med)
    core = r <= r_fit
    use = core & good
    out = dict(mjd=float(d["mjd"]), wave=float(d["wave"]), band=float(d["band"]),
               det=int(d["det"]), bkg=bkg, core_masked=float(1 - use.sum() / core.sum()),
               flux=np.nan, err=np.nan, ap=np.nan, ap_err=np.nan,
               core_bits=int(np.bitwise_or.reduce(d["flags"][r <= 1.5].ravel())))
    if not np.isfinite(bkg) or use.sum() < 4 or not np.any(d["psf"]):
        return out
    p = psf_model(d)
    y = (img - bkg)[use]
    w = 1.0 / d["variance"][use]
    pp = p[use]
    den = np.sum(w * pp * pp)
    if den > 0 and np.sum(p[use]) > 0.3 * np.sum(p[core]):  # need >30% of PSF unmasked
        out["flux"] = float(np.sum(w * pp * y) / den) * MJYSR_TO_UJY
        out["err"] = float(1.0 / np.sqrt(den)) * MJYSR_TO_UJY
    ap = r <= 2.0
    if np.all(good[ap]):
        out["ap"] = float(np.sum(img[ap] - bkg)) * MJYSR_TO_UJY
        out["ap_err"] = float(np.sqrt(np.sum(d["variance"][ap]))) * MJYSR_TO_UJY
    return out


def bit_names(value: int) -> list[str]:
    names = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC",
             9: "MISSING_DATA", 10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS",
             15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE",
             22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM",
             27: "SNOWBALL", 28: "HALO"}
    return [n for b, n in names.items() if value & (1 << b)]
