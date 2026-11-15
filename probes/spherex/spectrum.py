"""Checks 3 and 4: wavelength sampling of one epoch, and a crude spectrum.

Usage: uv run --with matplotlib python spectrum.py <target> <start-date> [days]
  e.g. spectrum.py eps_ind_b 2025-09-28 14
Mode 'wing' (saturated stars): flux in a 5-9 px annulus instead of a PSF fit.
"""
import sys

import matplotlib
import numpy as np
from astropy.time import Time

from phot import IMG, MJYSR_TO_UJY, frames, get_stamps, good_mask, photometry

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BANDS = {"CH4 3.3": 3.3, "CO2 4.3": 4.3, "CO 4.6": 4.6, "H2O 1.4": 1.4, "H2O 1.9": 1.9, "H2O 2.7": 2.7}


def window(target: str, start: str, days: float) -> list[dict]:
    t0 = Time(start).mjd
    return [f for f in frames(target) if t0 <= f["mjd"] < t0 + days]


def wing_flux(d: dict, r_in: float = 5.0, r_out: float = 9.0, r_bkg: float = 12.0,
              min_good: float = 0.5) -> tuple[float, float]:
    """Zodi- and background-subtracted mean surface brightness in an annulus (MJy/sr).

    For saturated stars the core is masked out to r~4-6 px; the wing level scales with
    total flux if the PSF shape is stable, so it is a relative (not absolute) measure.
    """
    img = d["image"] - d["zodi"]
    good = good_mask(d)
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx + d["x0"] - d["xpix"], yy + d["y0"] - d["ypix"])
    bk = good & (r >= r_bkg)
    ring = good & (r >= r_in) & (r < r_out)
    if bk.sum() < 20 or ring.sum() < min_good * ((r >= r_in) & (r < r_out)).sum():
        return np.nan, np.nan
    bkg = np.median(img[bk])
    return float(np.mean(img[ring]) - bkg), float(np.sqrt(np.mean(d["variance"][ring]) / ring.sum()))


def coverage_report(ds: list[dict]) -> None:
    w = np.array([float(d["wave"]) for d in ds])
    b = np.array([float(d["band"]) for d in ds])
    o = np.argsort(w)
    w, b = w[o], b[o]
    lo, hi = w - b / 2, w + b / 2
    gaps = [(hi[i], lo[i + 1]) for i in range(len(w) - 1) if lo[i + 1] > hi[i]]
    covered = np.sum(np.minimum(hi, 5.0) - np.maximum(lo, 0.75)) / (5.0 - 0.75)
    print(f"  {len(w)} frames, {w.min():.3f}-{w.max():.3f} um; R=lambda/dlambda "
          f"median {np.median(w / b):.0f}; summed bandwidth / range = {covered:.2f}")
    big = sorted(gaps, key=lambda g: g[0] - g[1])[:6]
    print("  largest gaps (um):", ", ".join(f"{a:.3f}-{c:.3f}" for a, c in big))


def main(target: str, start: str, days: float = 14.0, mode: str = "psf") -> None:
    fs = window(target, start, days)
    print(f"{target} {start} +{days}d: {len(fs)} frames")
    ds = get_stamps(target, fs)
    coverage_report(ds)
    rows = []
    for d in ds:
        if mode == "wing":
            fl, er = wing_flux(d)
            rows.append(dict(wave=float(d["wave"]), band=float(d["band"]), det=int(d["det"]),
                             flux=fl, err=er, mjd=float(d["mjd"])))
        else:
            rows.append(photometry(d))
    ok = [r for r in rows if np.isfinite(r["flux"])]
    print(f"  measured {len(ok)}/{len(rows)} frames (rest masked)")
    unit = "wing surface brightness (MJy/sr, relative)" if mode == "wing" else "flux (mJy)"
    scale = 1.0 if mode == "wing" else 1e-3
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    for det in range(1, 7):
        rr = [r for r in ok if r["det"] == det]
        if rr:
            ax.errorbar([r["wave"] for r in rr], [r["flux"] * scale for r in rr],
                        yerr=[r["err"] * scale for r in rr], xerr=[r["band"] / 2 for r in rr],
                        fmt="o", ms=3, label=f"D{det}")
    for name, lam in BANDS.items():
        ax.axvline(lam, color="0.8", lw=0.8, zorder=0)
        ax.text(lam, 1.0, name, transform=ax.get_xaxis_transform(), fontsize=7,
                rotation=90, va="top", ha="right", color="0.5")
    ax.set_ylabel(unit)
    ax.set_title(f"SPHEREx {target}, {start} + {days:.0f} d, {len(ok)}/{len(rows)} frames "
                 f"({'annulus 5-9 px' if mode == 'wing' else 'PSF fit, zodi-subtracted'})")
    ax.legend(fontsize=7, ncol=6)
    for i, r in enumerate(sorted(rows, key=lambda r: r["wave"])):
        c = "C0" if np.isfinite(r["flux"]) else "C3"
        ax2.plot([r["wave"] - r["band"] / 2, r["wave"] + r["band"] / 2], [r["mjd"]] * 2, c, lw=2)
    ax2.set_ylabel("MJD")
    ax2.set_xlabel("wavelength at target (um)")
    ax2.set_xlim(0.7, 5.05)
    fig.tight_layout()
    out = IMG / f"spherex-spectrum-{target.replace('_', '-')}.png"
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    print(f"  wrote {out.relative_to(IMG.parents[2])}")
    np.save(out.with_suffix(".npy").as_posix().replace("docs/validation/img", "cache"), ok)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], float(a[2]) if len(a) > 2 else 14.0, a[3] if len(a) > 3 else "psf")
