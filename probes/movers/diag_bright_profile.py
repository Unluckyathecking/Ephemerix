"""Probe: per-frame matched-filter S/N around catalogued stars, by radius and G magnitude.

    PYTHONPATH=probes/movers uv run python probes/movers/diag_bright_profile.py B5 BarnardsStar
Reads cache/movers/diag/<field>.npz. Mean and rms of single-frame S/N (psi/sqrt(phi)) in
1-px annuli around Gaia stars, and the share of pixels masked (phi = 0), per G bin. A clean
subtraction gives mean 0 and rms 1 outside the mask.
"""
from __future__ import annotations

import sys

import numpy as np

from diag_bright_catalog import load

G_BINS = ((7.5, 9.0), (9.0, 10.5), (10.5, 12.0), (12.0, 13.5))
R_EDGES = np.arange(0, 21)


def profile(name: str, root: str = "cache/movers/diag") -> dict:
    z = np.load(f"{root}/{name}.npz")
    psi, phi = z["psi"], z["phi"]
    with np.errstate(invalid="ignore", divide="ignore"):
        snr = np.where(phi > 0, psi / np.sqrt(np.where(phi > 0, phi, 1)), np.nan)
    cat = load(name)["gaia"]
    n = psi.shape[1]
    yy, xx = np.mgrid[0:n, 0:n]
    out = {}
    for lo, hi in G_BINS:
        sel = (cat["g"] >= lo) & (cat["g"] < hi)
        sel &= (cat["x"] > 5) & (cat["x"] < n - 5) & (cat["y"] > 5) & (cat["y"] < n - 5)
        rows = []
        for r0, r1 in zip(R_EDGES[:-1], R_EDGES[1:]):
            vals, masked = [], []
            for x, y in zip(cat["x"][sel], cat["y"][sel]):
                ring = (np.hypot(xx - x, yy - y) >= r0) & (np.hypot(xx - x, yy - y) < r1)
                v = snr[:, ring]
                vals.append(v[np.isfinite(v)])
                masked.append(np.mean(~np.isfinite(v)))
            v = np.concatenate(vals) if vals else np.zeros(0)
            rows.append((r0, float(np.mean(v)) if v.size else np.nan,
                         float(np.sqrt(np.mean(v ** 2))) if v.size else np.nan,
                         float(np.mean(masked)) if masked else np.nan))
        out[(lo, hi)] = (int(sel.sum()), rows)
    return out


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print("==", name)
        for (lo, hi), (k, rows) in profile(name).items():
            print(f"  G {lo}-{hi} ({k} stars): r mean/rms/masked " + "  ".join(
                f"{r}:{m:+.2f}/{s:.2f}/{f:.2f}" for r, m, s, f in rows[1:16]))
