"""Relative brightness vs time from per-exposure SPHEREx photometry.

Method: every exposure sees the source at a different wavelength, so a raw flux series mixes
spectrum and variability. Divide each exposure's flux by the object's own time-averaged
spectrum at that wavelength (median of all exposures on the same detector within +-hw of it,
from every epoch), giving rel = 1 when the source is at its mean brightness. The same
statistic on comparison stars measured in the same frames is the noise floor.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LC = ROOT / "cache" / "variables" / "lc"
BANDS = {1: (0.75, 1.10), 2: (1.10, 1.65), 3: (1.65, 2.42), 4: (2.42, 3.82), 5: (3.82, 4.42), 6: (4.42, 5.00)}


def load(slug: str) -> dict:
    return json.loads((LC / f"{slug}.json").read_text())


def robust_std(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return np.nan
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def relative(wl: np.ndarray, det: np.ndarray, flux: np.ndarray, err: np.ndarray,
             frac: float = 1 / 80, min_n: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """flux / (median flux of same-detector exposures within +-wl*frac), and its error."""
    rel = np.full(len(flux), np.nan)
    rerr = np.full(len(flux), np.nan)
    ok = np.isfinite(flux) & np.isfinite(err)
    for i in np.where(ok)[0]:
        near = ok & (det == det[i]) & (np.abs(wl - wl[i]) <= wl[i] * frac)
        if near.sum() >= min_n:
            tmpl = np.median(flux[near])
            if tmpl > 0:
                rel[i], rerr[i] = flux[i] / tmpl, err[i] / tmpl
    return rel, rerr


def series(d: dict, who: str | None = None) -> dict[str, np.ndarray]:
    """Arrays for the target (who=None) or a comparison star, with relative brightness."""
    rows = d["rows"]
    if who is None:
        flux = np.array([r["flux"] if not r["reason"] else np.nan for r in rows], float)
        err = np.array([r["err"] if not r["reason"] else np.nan for r in rows], float)
        wl = np.array([r["wl"] for r in rows], float)
    else:
        c = [r["comps"].get(who) for r in rows]
        flux = np.array([x[0] if x and not x[2] else np.nan for x in c], float)
        err = np.array([x[1] if x and not x[2] else np.nan for x in c], float)
        wl = np.array([x[3] if x else np.nan for x in c], float)
    det = np.array([r["det"] for r in rows])
    mjd = np.array([r["mjd"] for r in rows], float)
    rel, rerr = relative(wl, det, flux, err)
    return {"mjd": mjd, "det": det, "wl": wl, "flux": flux, "err": err, "rel": rel, "rerr": rerr}


def sine_fit(t: np.ndarray, y: np.ndarray, e: np.ndarray, period: float, harmonics: int = 1):
    """Weighted fit y = c + sum a_k cos + b_k sin at fixed period. Returns (coef, cov, model fn, chi2, chi2_const)."""
    ok = np.isfinite(y) & np.isfinite(e) & (e > 0)
    t, y, e = t[ok], y[ok], e[ok]
    def design(tt):
        cols = [np.ones_like(tt)]
        for k in range(1, harmonics + 1):
            ph = 2 * np.pi * k * tt / period
            cols += [np.cos(ph), np.sin(ph)]
        return np.vstack(cols).T
    A = design(t) / e[:, None]
    coef, *_ = np.linalg.lstsq(A, y / e, rcond=None)
    cov = np.linalg.inv(A.T @ A)
    chi2 = float(np.sum(((y - design(t) @ coef) / e) ** 2))
    wmean = np.sum(y / e**2) / np.sum(1 / e**2)
    chi2c = float(np.sum(((y - wmean) / e) ** 2))
    return coef, cov, (lambda tt: design(np.atleast_1d(tt)) @ coef), chi2, chi2c, int(ok.sum())


def clip_mask(y: np.ndarray, nsig: float = 5.0) -> np.ndarray:
    """Keep points within nsig robust sigma of the median. About 2% of frames return a near-zero
    flux with a small formal error (a dropout, not a dimming); this removes them before averaging."""
    if len(y) < 4:
        return np.ones(len(y), bool)
    s = robust_std(y)
    if not np.isfinite(s) or s == 0:
        return np.ones(len(y), bool)
    return np.abs(y - np.median(y)) <= nsig * s


def bin_epochs(t: np.ndarray, y: np.ndarray, e: np.ndarray, gap: float = 1.0, min_n: int = 3):
    """Inverse-variance means of y within groups split at time gaps > gap days.

    Error is the larger of the formal error and scatter/sqrt(n), so it is never optimistic.
    """
    ok = np.isfinite(y) & np.isfinite(e) & (e > 0)
    t, y, e = t[ok], y[ok], e[ok]
    o = np.argsort(t)
    t, y, e = t[o], y[o], e[o]
    out = []
    for g in np.split(np.arange(len(t)), np.where(np.diff(t) > gap)[0] + 1):
        g = g[clip_mask(y[g])]
        if len(g) < min_n:
            continue
        w = 1 / e[g] ** 2
        m = np.sum(w * y[g]) / np.sum(w)
        formal = 1 / np.sqrt(np.sum(w))
        emp = robust_std(y[g]) / np.sqrt(len(g))
        out.append((float(np.mean(t[g])), float(m), float(max(formal, emp if np.isfinite(emp) else 0)),
                    len(g), float(t[g].min()), float(t[g].max())))
    return out
