"""Plot: RW Aur NEOWISE per-visit medians (saturated regime) and the SPHEREx noise floor from two constant
Ks~9 comparison stars measured in RW Aur's frames. Cached data only. Writes docs/validation/img/var-rw-aur.png."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time
from analysis import ROOT, load, series, bin_epochs, robust_std
from wise_brief import get

fig, ax = plt.subplots(2, 1, figsize=(9, 7.5))
for t in get("RW Aur"):
    tab = t["table"][0]
    m = np.asarray(t["mjd"], float); o = np.argsort(m); m = m[o]
    for band, c in (("w1mpro", "#5b5bd6"), ("w2mpro", "#c0392b")):
        v = np.asarray(t[band], float)[o]
        g = np.split(np.arange(len(m)), np.where(np.diff(m) > 30)[0] + 1)
        mm = np.array([m[i].mean() for i in g]); med = np.array([np.nanmedian(v[i]) for i in g])
        sc = np.array([robust_std(v[i]) for i in g])
        ax[0].errorbar(Time(mm, format="mjd").datetime, med, sc, fmt="o-" if tab != "allwise_p3as_mep" else "s", color=c, ms=4, lw=.8,
                       label=f"{band[:2].upper()} ({'NEOWISE' if tab.startswith('neo') else 'AllWISE'})")
ax[0].invert_yaxis(); ax[0].legend(fontsize=8, ncol=2)
ax[0].set_ylabel("per-visit median (mag)\nbars: scatter within visit")
ax[0].set_title("RW Aurigae in WISE/NEOWISE: saturated (W1 < 8, W2 < 6.7), so relative and indicative only")
d = load("rw-aur")
cols = {1: "#5b5bd6", 4: "#e9a23b", 5: "#2a9d8f", 6: "#c0392b"}
for j, (name, *_) in enumerate(d["comps"]):
    x = series(d, name)
    for k, c in cols.items():
        m = (x["det"] == k) & np.isfinite(x["rel"])
        if m.sum() < 5: continue
        for t, v, e, n, *_ in bin_epochs(x["mjd"][m], x["rel"][m], x["rerr"][m], gap=20, min_n=3):
            ax[1].errorbar(Time(t, format="mjd").datetime, v, e, fmt="os"[j], color=c, ms=5, label=f"D{k} {name}" if True else None)
h, l = ax[1].get_legend_handles_labels(); u = dict(zip(l, h))
ax[1].legend(u.values(), u.keys(), fontsize=7, ncol=2)
ax[1].axhline(1, color="k", lw=.5); ax[1].set_ylim(0.9, 1.1)
ax[1].set_ylabel("pass mean / overall mean")
ax[1].set_title("SPHEREx noise floor: two constant Ks~9 stars in RW Aur's frames agree pass to pass within 1-2%.\n"
                "RW Aur itself: 21 of 335 exposures unsaturated (19 at 0.75-1.1 µm), too few for a light curve.", fontsize=9)
fig.tight_layout()
fig.savefig(ROOT / "docs/validation/img/var-rw-aur.png", dpi=110)
print("ok")
