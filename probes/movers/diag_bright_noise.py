"""Probe: is the stacked S/N unit-variance on random tracks, and is the single-frame one?

    uv run python probes/movers/diag_bright_noise.py Haumea B6 BarnardsStar
Reads cache/movers/diag/<field>.npz. For 12 random linear tracks of 3-6 px/day, the stacked
S/N map sum(psi)/sqrt(sum(phi)) over start pixels: its rms, robust sigma (MAD) and share
above 4. Also the single-frame S/N rms vs its MAD (the search normalises by MAD).
"""
from __future__ import annotations

import sys

import numpy as np


def stack(psi: np.ndarray, phi: np.ndarray, off: np.ndarray) -> np.ndarray:
    n, h, w = psi.shape
    pad = int(np.abs(off).max()) + 1
    p = np.pad(psi, ((0, 0), (pad, pad), (pad, pad)))
    q = np.pad(phi, ((0, 0), (pad, pad), (pad, pad)))
    sp = np.zeros((h, w))
    sq = np.zeros((h, w))
    for i in range(n):
        ox, oy = off[0, i], off[1, i]
        sp += p[i, pad + oy:pad + oy + h, pad + ox:pad + ox + w]
        sq += q[i, pad + oy:pad + oy + h, pad + ox:pad + ox + w]
    full = np.median(sq[sq > 0])
    return np.where(sq >= 0.3 * full, sp / np.sqrt(np.where(sq > 0, sq, 1)), np.nan)


def mad(v: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    for name in sys.argv[1:]:
        z = np.load(f"cache/movers/diag/{name}.npz")
        psi, phi, dt = z["psi"], z["phi"], z["dt"]
        with np.errstate(invalid="ignore", divide="ignore"):
            one = (psi / np.sqrt(np.where(phi > 0, phi, np.nan)))
        v1 = one[np.isfinite(one)]
        rms, rob, tail = [], [], []
        for _ in range(12):
            rate = rng.uniform(3, 6)
            a = rng.uniform(0, 2 * np.pi)
            off = np.rint(np.outer([np.cos(a), np.sin(a)], dt) * rate).astype(int)
            s = stack(psi, phi, off)
            v = s[np.isfinite(s)]
            rms.append(np.std(v))
            rob.append(mad(v))
            tail.append(np.mean(np.abs(v) > 4))
        print(f"{name:12s} single-frame rms {np.std(v1):.2f} MAD {mad(v1):.2f} |S/N|>4 "
              f"{np.mean(np.abs(v1) > 4):.4f} | stacked rms {np.mean(rms):.2f} MAD "
              f"{np.mean(rob):.2f} |S/N|>4 {np.mean(tail):.5f} (Gaussian 0.00006)")


def static_removed(psi: np.ndarray, phi: np.ndarray, det: np.ndarray) -> np.ndarray:
    """psi with each detector's per-pixel median flux over the pass taken out (offline
    approximation of subtracting the pass-median difference image)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(phi > 0, psi / np.where(phi > 0, phi, 1), np.nan)
    out = psi.copy()
    for d in np.unique(det):
        k = det == d
        med = np.nan_to_num(np.nanmedian(f[k], axis=0))
        out[k] = psi[k] - med[None] * phi[k]
    return out


def halo_masked(psi: np.ndarray, phi: np.ndarray, masked: np.ndarray, scale: float):
    """Zero psi/phi within scale x r_eq of each mostly-masked blob (r_eq = sqrt(area/pi))."""
    from scipy import ndimage
    lab, n = ndimage.label(masked > 0.5)
    grow = np.zeros(masked.shape, bool)
    yy, xx = np.mgrid[0:masked.shape[0], 0:masked.shape[1]]
    for j, sl in enumerate(ndimage.find_objects(lab), 1):
        blob = lab == j
        r = np.sqrt(blob.sum() / np.pi)
        cy, cx = ndimage.center_of_mass(blob)
        grow |= np.hypot(xx - cx, yy - cy) <= (1 + scale) * r
    return np.where(grow, 0, psi), np.where(grow, 0, phi), float(grow.mean())


def report(tag: str, psi, phi, dt, rng) -> None:
    rms, rob, tail = [], [], []
    for _ in range(12):
        rate, a = rng.uniform(3, 6), rng.uniform(0, 2 * np.pi)
        off = np.rint(np.outer([np.cos(a), np.sin(a)], dt) * rate).astype(int)
        v = stack(psi, phi, off)
        v = v[np.isfinite(v)]
        rms.append(np.std(v))
        rob.append(mad(v))
        tail.append(np.mean(np.abs(v) > 4))
    print(f"   {tag:22s} stacked rms {np.mean(rms):.2f} MAD {np.mean(rob):.2f} "
          f"|S/N|>4 {np.mean(tail):.5f}")


def variants(name: str, root: str = "cache/movers/diag") -> None:
    rng = np.random.default_rng(1)
    z = np.load(f"{root}/{name}.npz")
    psi, phi, dt = z["psi"], z["phi"], z["dt"]
    print(name)
    report("as searched", psi, phi, dt, rng)
    report("static removed", static_removed(psi, phi, z["det"]), phi, dt, rng)
    for s in (0.5, 1.0):
        p, q, f = halo_masked(psi, phi, z["masked"], s)
        report(f"halo x{s} (mask {f:.2f})", p, q, dt, rng)
