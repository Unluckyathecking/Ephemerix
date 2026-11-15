"""Check 6: per-epoch stacked stamps and centroid shifts against proper motion.

Usage: uv run --with matplotlib python epochs.py barnard
Barnard's Star saturates every detector, so the per-frame centroid is the centre of
the saturation footprint (pixels that are NaN or carry OVERFLOW/SUR_ERROR within 6 px),
converted to sky coordinates with that frame's WCS. Stacks use a FIXED sky grid so the
motion shows. Writes docs/validation/img/spherex-epochs-<target>.png.
"""
import sys

import matplotlib
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.time import Time

from phot import IMG, frame_wcs, frames, get_stamps
from query import group_epochs
from stack import combine, grid_wcs, resample
from targets import coord_at

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

WINDOWS = {"1.62-1.80 um": (3, 1.62, 1.80), "4.4-4.8 um": (6, 4.4, 4.8)}
SAT_BITS = (1 << 1) | (1 << 2)  # OVERFLOW | SUR_ERROR
N = 21


def footprint_centroid(d: dict) -> tuple[float, float] | None:
    """Sky position of the saturation footprint centre (None if not saturated)."""
    ny, nx = d["image"].shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx + d["x0"] - d["xpix"], yy + d["y0"] - d["ypix"])
    sat = ((d["flags"] & SAT_BITS) != 0) | ~np.isfinite(d["image"])
    sat &= r < 6
    if sat.sum() < 3:
        return None
    fx = float(xx[sat].mean() + d["x0"])
    fy = float(yy[sat].mean() + d["y0"])
    ra, dec = frame_wcs(d).pixel_to_world_values(fx, fy)
    return float(ra), float(dec)


def main(target: str) -> None:
    sel = {}
    for name, (det, lo, hi) in WINDOWS.items():
        fs = [f for f in frames(target) if f["detector"] == det]
        sel[name] = [d for d in get_stamps(target, fs) if lo <= float(d["wave"]) < hi]
    alld = [d for v in sel.values() for d in v]
    eps = [(a, b) for a, b, n in group_epochs([float(d["mjd"]) for d in alld]) if n >= 4]
    ref = coord_at(target, Time(eps[0][0], format="mjd"))
    gw = grid_wcs(ref.ra.deg, ref.dec.deg, N)
    fig, axes = plt.subplots(len(WINDOWS), len(eps), figsize=(2.6 * len(eps), 2.9 * len(WINDOWS)))
    print(f"fixed grid centred on {target} at {Time(eps[0][0], format='mjd').iso[:10]}")
    meas = {}
    for j, (a, b) in enumerate(eps):
        tmid = Time((a + b) / 2, format="mjd")
        pred = coord_at(target, tmid)
        ppx, ppy = (float(v) for v in gw.world_to_pixel_values(pred.ra.deg, pred.dec.deg))
        cents = []
        for i, (name, ds) in enumerate(sel.items()):
            sub = [d for d in ds if a <= float(d["mjd"]) <= b]
            ax = axes[i, j]
            ax.set_xticks([])
            ax.set_yticks([])
            for d in sub:
                c = footprint_centroid(d)
                if c:
                    # offset from this frame's own prediction, so mixed dates within a pass are fine
                    p = coord_at(target, float(d["mjd"]))
                    cents.append(((c[0] - p.ra.deg) * np.cos(np.radians(p.dec.deg)) * 3600,
                                  (c[1] - p.dec.deg) * 3600))
            if not sub:
                continue
            im, _, _ = combine([resample(d, ref.ra.deg, ref.dec.deg, N) for d in sub])
            v = np.nanpercentile(im, [5, 99.5])
            cmap = plt.get_cmap("magma").copy()
            cmap.set_bad("0.45")  # masked (saturated) pixels in grey
            ax.imshow(np.arcsinh(im / max(v[1] / 50, 1e-3)), origin="lower", cmap=cmap)
            ax.plot((N - 1) / 2, (N - 1) / 2, "x", color="lime", ms=9, mew=1.5)
            ax.plot(ppx, ppy, "+", color="cyan", ms=16, mew=1.5)
            ax.set_title(f"{name}\n{Time(a, format='mjd').iso[:10]}, {len(sub)} fr", fontsize=7)
        cc = np.array(cents)
        if len(cc):
            mu = cc.mean(0)
            se = cc.std(0, ddof=1) / np.sqrt(len(cc)) if len(cc) > 1 else np.array([np.nan] * 2)
            meas[(a, b)] = (tmid, mu, se, len(cc))
            print(f"epoch {Time(a, format='mjd').iso[:10]}..{Time(b, format='mjd').iso[:10]}: "
                  f"n={len(cc)} measured - predicted = ({mu[0]:+.2f} +- {se[0]:.2f}, "
                  f"{mu[1]:+.2f} +- {se[1]:.2f}) arcsec (E, N)")
    keys = list(meas)
    for k0, k1 in zip(keys, keys[1:]):
        t0, m0, s0, _ = meas[k0]
        t1, m1, s1, _ = meas[k1]
        p0, p1 = coord_at(target, t0), coord_at(target, t1)
        dra, ddec = SkyCoord(p0.ra, p0.dec).spherical_offsets_to(SkyCoord(p1.ra, p1.dec))
        pred = np.array([dra.to(u.arcsec).value, ddec.to(u.arcsec).value])
        got = pred + (m1 - m0)
        err = np.hypot(s0, s1)
        print(f"{t0.iso[:10]} -> {t1.iso[:10]} ({(t1 - t0).jd / 365.25:.2f} yr): predicted shift "
              f"({pred[0]:+.2f}, {pred[1]:+.2f})\" = {np.hypot(*pred) / 6.15:.2f} px; measured "
              f"({got[0]:+.2f}, {got[1]:+.2f})\" +- ({err[0]:.2f}, {err[1]:.2f}); "
              f"residual {np.hypot(*(got - pred)):.2f}\"")
    fig.suptitle(f"SPHEREx {target} per-epoch stacks on a fixed sky grid (north up, 6.15\"/px)\n"
                 f"grey = saturated/masked; green x = position at first epoch; cyan + = predicted", fontsize=7)
    fig.tight_layout(h_pad=1.5)
    out = IMG / f"spherex-epochs-{target.replace('_', '-')}.png"
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1])
