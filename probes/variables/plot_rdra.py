"""Plot: R Dra relative brightness from SPHEREx PSF wings vs date (with a constant control star),
and NEOWISE per-visit medians vs VSX phase. Writes docs/validation/img/var-r-dra.png."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time

from analysis import LC, ROOT, relative, robust_std, sine_fit
from wise_brief import get

P, T0 = 246.12, 2457370.0 - 2400000.5
COL = {1: "#5b5bd6", 6: "#c0392b"}  # only the bands that passed verify.py (15 Nov)
LAB = {1: "0.75-1.1 µm", 3: "1.65-2.4 µm", 4: "2.4-3.8 µm", 6: "4.4-5.0 µm"}


def load(name):
    d = json.loads((LC / f"{name}-wing.json").read_text())["rows"]
    mjd = np.array([r["mjd"] for r in d]); det = np.array([r["det"] for r in d]); wl = np.array([r["wl"] for r in d])
    f = np.array([np.nan if r["wing"] is None else r["wing"] for r in d], float)
    rel, _ = relative(wl, det, f, np.ones_like(f), frac=1 / 60, min_n=4)
    return mjd, det, rel


def main():
    fig, ax = plt.subplots(3, 1, figsize=(9, 11), gridspec_kw={"height_ratios": [3, 1.4, 2]})
    mjd, det, rel = load("r-dra")
    tt = np.linspace(mjd.min(), mjd.max(), 600)
    for k in COL:
        s = (det == k) & np.isfinite(rel)
        if s.sum() < 15:
            continue
        sig = robust_std(rel[s] - sine_fit(mjd[s] - T0, rel[s], np.full(s.sum(), .1), P)[2](mjd[s] - T0))
        model = sine_fit(mjd[s] - T0, rel[s], np.full(s.sum(), sig), P)[2]
        x = Time(mjd[s], format="mjd").datetime
        ax[0].plot(x, rel[s], "o", ms=3, color=COL[k], alpha=.55, label=f"{LAB[k]} (n={s.sum()})")
        ax[0].plot(Time(tt, format="mjd").datetime, model(tt - T0), "-", color=COL[k], lw=1.5)
    for n in range(14, 17):
        m = T0 + n * P
        if mjd.min() - 30 < m < mjd.max() + 30:
            ax[0].axvline(Time(m, format="mjd").datetime, color="k", ls=":", lw=1)
            ax[0].text(Time(m, format="mjd").datetime, ax[0].get_ylim()[1] if False else 2.25, " predicted\n maximum", fontsize=8, va="top")
    ax[0].set_ylim(0, 2.3)
    ax[0].set_ylabel("brightness / its average\n(from unsaturated PSF wings)")
    ax[0].set_title("R Draconis (Mira, P = 246 d): SPHEREx saturates the core; the outer PSF wings still trace the cycle")
    ax[0].legend(fontsize=8, ncol=2, loc="lower left")
    # control
    cm, cd, cr = load("control-2m1640")
    for k in COL:
        s = (cd == k) & np.isfinite(cr)
        ax[1].plot(Time(cm[s], format="mjd").datetime, cr[s], "o", ms=3, color=COL[k], alpha=.55)
    ax[1].set_ylim(0, 2.3)
    ax[1].axhline(1, color="k", lw=.5)
    ax[1].set_ylabel("control star\n(K giant, same method)")
    # NEOWISE
    for t in get("R Dra"):
        if t["table"][0] != "neowiser_p1bs_psd":
            continue
        m = np.asarray(t["mjd"], float); o = np.argsort(m); m = m[o]
        for band, c in (("w1mpro", "#5b5bd6"), ("w2mpro", "#c0392b")):
            v = np.asarray(t[band], float)[o]
            g = np.split(np.arange(len(m)), np.where(np.diff(m) > 30)[0] + 1)
            mm = np.array([m[i].mean() for i in g]); med = np.array([np.nanmedian(v[i]) for i in g])
            sc = np.array([robust_std(v[i]) / np.sqrt(len(i)) for i in g])
            ph = ((mm - T0) / P) % 1
            for off in (0, 1):
                ax[2].errorbar(ph + off, med, sc, fmt="o", color=c, ms=4, label=band[:2].upper() if off == 0 else None)
    ax[2].invert_yaxis()
    ax[2].set_xlabel("phase in the 246-day cycle (0 = predicted visual maximum, VSX ephemeris)")
    ax[2].set_ylabel("NEOWISE per-visit median (mag)\nsaturated: relative only")
    ax[2].legend(fontsize=8)
    ax[2].set_title("NEOWISE 2014-2024, 22 visits folded on the same ephemeris", fontsize=10)
    fig.tight_layout()
    out = ROOT / "docs" / "validation" / "img" / "var-r-dra.png"
    fig.savefig(out, dpi=110)
    print("wrote", out)


if __name__ == "__main__":
    main()
