"""Probe: characterise S/N >= 7 peaks from diag_bright dumps (cache/movers/diag/<field>.npz).

    uv run python probes/movers/diag_bright_stats.py BarnardsStar WISE0855 Haumea B6 B5
For each real and null peak: nearest Gaia star (G < 13) over its track, flag bits on the
track, the share of S/N carried by the top frames, detector of those frames, track rate.
"""
from __future__ import annotations

import sys

import numpy as np

from diag_bright_catalog import load
from pxs.spherex.config import FLAG_BITS

CUT = 7.0
BITS = ("PERSIST", "NONLINEAR", "OVERFLOW", "SUR_ERROR", "GHOST", "GHOST_FPA", "GHOST_EXT",
        "CROSSTALK", "HALO", "BLOOM", "SOURCE", "STREAK", "OUTLIER", "TRANSIENT")


def nearest_star(track: np.ndarray, use: np.ndarray, cat: dict, gmax: float):
    b = cat["g"] < gmax
    sx, sy = cat["x"][b], cat["y"][b]
    if not sx.size:
        return np.inf, np.nan
    d = np.hypot(track[0][use][:, None] - sx[None], track[1][use][:, None] - sy[None])
    j = np.argmin(d.min(axis=0))
    return float(d[:, j].min()), float(cat["g"][b][j])


def describe(z, cat, tag: str) -> list[dict]:
    rows = []
    snr = z[f"{tag}_snr"]
    for k in np.flatnonzero(snr >= CUT):
        psi, phi = z[f"{tag}_psi"][k], z[f"{tag}_phi"][k]
        use = phi > 0
        tot = np.sqrt(phi[use].sum())
        contrib = np.where(use, psi / tot, 0)
        top = np.argsort(contrib)[::-1][:3]
        fl = z[f"{tag}_flags"][k][use]
        tr = z[f"{tag}_track"][k]
        span = np.hypot(tr[0] - z[f"{tag}_x"][k], tr[1] - z[f"{tag}_y"][k]).max()
        d13, g13 = nearest_star(tr, use, cat, 13.0)
        d10, g10 = nearest_star(tr, use, cat, 10.5)
        rows.append({
            "tag": tag, "x": int(z[f"{tag}_x"][k]), "y": int(z[f"{tag}_y"][k]),
            "snr": float(snr[k]), "raw": float(z[f"{tag}_snr_raw"][k]),
            "top3": float(contrib[top].sum() / max(snr[k], 1e-6)),
            "top_det": tuple(int(z["det"][i]) for i in top),
            "top_wave": tuple(round(float(z["wave"][i]), 2) for i in top),
            "span": float(span), "d13": d13, "g13": g13, "d10": d10, "g10": g10,
            "refmax": float(np.nanmax(z[f"{tag}_ref"][k][use])) if use.any() else np.nan,
            "flags": {b: float(np.mean((fl >> FLAG_BITS[b]) & 1)) for b in BITS}})
    return rows


def main(names: list[str]) -> None:
    for name in names:
        z = np.load(f"cache/movers/diag/{name}.npz")
        cat = load(name)["gaia"]
        n = z["img"].shape[0]
        yy, xx = np.mgrid[0:n, 0:n]
        b = cat["g"] < 10.5
        dmap = np.min(np.hypot(xx[..., None] - cat["x"][b], yy[..., None] - cat["y"][b]),
                      axis=-1) if b.any() else np.full((n, n), np.inf)
        frac = {r: float(np.mean(dmap < r)) for r in (10, 20, 40)}
        fc = z["flag_counts"].astype(float) / len(z["mjd"])
        print(f"== {name}: frames {len(z['mjd'])}, G<10.5 stars {int(b.sum())}, "
              f"area within 10/20/40 px of them {frac}")
        print("   field-mean flag rate: " + ", ".join(
            f"{k} {fc[FLAG_BITS[k]].mean():.3f}" for k in BITS if fc[FLAG_BITS[k]].mean() > 0))
        for tag in ("real", "null"):
            rows = describe(z, cat, tag)
            for r in rows:
                fl = " ".join(f"{k}:{v:.2f}" for k, v in r["flags"].items() if v > 0.05)
                print(f"  {tag} ({r['x']:3d},{r['y']:3d}) snr {r['snr']:5.1f} raw {r['raw']:5.1f}"
                      f" top3 {r['top3']:.2f} det {r['top_det']} wave {r['top_wave']}"
                      f" span {r['span']:4.1f} | G<13 d {r['d13']:5.1f} (G {r['g13']:.1f})"
                      f" G<10.5 d {r['d10']:5.1f} | refmax {r['refmax']:.2f} | {fl}")
            if rows:
                d10 = np.array([r["d10"] for r in rows])
                print(f"  {tag}: {len(rows)} peaks; within 20/40 px of a G<10.5 star: "
                      f"{int((d10 < 20).sum())}/{int((d10 < 40).sum())}; median top3 share "
                      f"{np.median([r['top3'] for r in rows]):.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
