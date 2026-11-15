"""Check 5: is a faint cold brown dwarf detected at 3.8-5 um after stacking?

Usage: uv run --with matplotlib python faint.py wise0855
Uses D5+D6 frames (whose wavelength at the target is 3.8-5.0 um), groups by pass,
forced PSF photometry at the PM-predicted position per frame, and inverse-variance
stacks. Writes docs/validation/img/spherex-stack-<target>.png.
"""
import sys

import matplotlib
import numpy as np
from astropy.time import Time

from phot import IMG, frames, get_stamps
from query import group_epochs
from stack import combine, forced_stack, resample

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

WINDOWS = {"3.8-4.4 um": (3.8, 4.4), "4.4-5.0 um": (4.4, 5.0), "3.8-5.0 um": (3.8, 5.0)}


def main(target: str) -> None:
    fs = [f for f in frames(target) if f["detector"] in (5, 6)]
    ds = [d for d in get_stamps(target, fs) if 3.8 <= float(d["wave"]) <= 5.0]
    eps = group_epochs([float(d["mjd"]) for d in ds])
    groups = {}
    for a, b, _ in eps:
        sel = [d for d in ds if a <= float(d["mjd"]) <= b]
        if len(sel) >= 5:
            groups[f"{Time(a, format='mjd').iso[:10]} (n={len(sel)})"] = sel
    groups["all passes"] = ds
    fig, axes = plt.subplots(len(groups), 2, figsize=(5.5, 2.6 * len(groups)))
    for gi, (gname, sel) in enumerate(groups.items()):
        for wname, (lo, hi) in WINDOWS.items():
            sub = [d for d in sel if lo <= float(d["wave"]) < hi]
            if len(sub) < 3:
                continue
            r = forced_stack(sub)
            print(f"{gname:28s} {wname}: n={r['n']:3d} flux={r['flux']:7.1f} +- {r['err']:5.1f} uJy "
                  f"S/N(var)={r['snr_var']:5.1f}  empty-aperture sigma={r['sig_empty']:5.1f} "
                  f"S/N(empty)={r['snr_empty']:5.1f}")
        for j, (lo, hi) in enumerate([(3.8, 4.4), (4.4, 5.0)]):
            sub = [d for d in sel if lo <= float(d["wave"]) < hi]
            ax = axes[gi, j]
            ax.set_xticks([])
            ax.set_yticks([])
            if not sub:
                continue
            im, var, nn = combine([resample(d, float(d["ra"]), float(d["dec"])) for d in sub])
            s = np.nanstd(im[np.hypot(*np.mgrid[-10:11, -10:11]) > 5])
            ax.imshow(im, origin="lower", cmap="gray_r", vmin=-3 * s, vmax=6 * s)
            ax.plot(10, 10, "r+", ms=14, mew=0.8)
            ax.set_title(f"{gname}\n{lo}-{hi} um, {len(sub)} frames", fontsize=7)
    fig.suptitle(f"SPHEREx {target}: PM-shifted stacks (north up, 6.15\"/px, red + = predicted)",
                 fontsize=8)
    fig.tight_layout()
    out = IMG / f"spherex-stack-{target.replace('_', '-')}.png"
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")


def binned_spectrum(target: str, width: float = 0.1) -> None:
    """All-pass 3.8-5 um spectrum: per-frame PSF fluxes and inverse-variance 0.1 um bins."""
    from phot import photometry
    from stack import wmean
    fs = [f for f in frames(target) if f["detector"] in (5, 6)]
    rows = [photometry(d) for d in get_stamps(target, fs) if 3.8 <= float(d["wave"]) <= 5.0]
    w = np.array([r["wave"] for r in rows])
    f = np.array([r["flux"] for r in rows])
    e = np.array([r["err"] for r in rows])
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.errorbar(w, f, e, fmt=".", color="0.7", label="single frames")
    edges = np.arange(3.8, 5.0001, width)
    for lo in edges[:-1]:
        m = (w >= lo) & (w < lo + width)
        mu, sig = wmean(f[m], e[m])
        ax.errorbar(lo + width / 2, mu, sig, xerr=width / 2, fmt="o", color="C3")
        print(f"  {lo:.1f}-{lo + width:.1f} um: n={m.sum():2d} {mu:6.0f} +- {sig:4.0f} uJy")
    ax.axhline(0, color="k", lw=0.5)
    for lam, name in [(4.3, "CO2"), (4.6, "CO")]:
        ax.axvline(lam, color="0.8", lw=0.8)
        ax.text(lam, 0.97, name, transform=ax.get_xaxis_transform(), fontsize=7, va="top")
    ax.set_xlabel("wavelength (um)")
    ax.set_ylabel("flux (uJy)")
    ax.set_title(f"SPHEREx {target}, all passes, PM-corrected forced PSF photometry")
    fig.tight_layout()
    fig.savefig(IMG / f"spherex-spectrum-{target.replace('_', '-')}.png", dpi=110)


if __name__ == "__main__":
    main(sys.argv[1])
    binned_spectrum(sys.argv[1])
