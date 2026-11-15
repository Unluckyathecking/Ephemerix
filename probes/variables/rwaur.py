"""RW Aur: which exposures are measurable, and does matched-wavelength brightness change between passes?"""
import numpy as np
from collections import Counter
from analysis import load, series, bin_epochs, robust_std, BANDS
d = load("rw-aur")
print("frames", d["frames_by_collection"], "read", d["n_read"])
print("reasons:", Counter(r["reason"] or "ok" for r in d["rows"]))
s = series(d)
ok = np.isfinite(s["flux"])
for k in range(1, 7):
    m = s["det"] == k
    print(f"D{k}: {m.sum()} frames, {(m & ok).sum()} measured; measured wl {np.nanmin(s['wl'][m&ok]) if (m&ok).any() else 0:.2f}-{np.nanmax(s['wl'][m&ok]) if (m&ok).any() else 0:.2f}")
for who in [None] + [c[0] for c in d["comps"]]:
    x = series(d, who)
    print("==", who or "RW Aur")
    for k in range(1, 7):
        m = (x["det"] == k) & np.isfinite(x["rel"])
        if m.sum() < 5: continue
        bins = bin_epochs(x["mjd"][m], x["rel"][m], x["rerr"][m], gap=20, min_n=3)
        print(f"  D{k} scatter {robust_std(x['rel'][m]):.3f}: " + "  ".join(f"{t:.0f}:{v:.3f}±{e:.3f}(n{n})" for t, v, e, n, *_ in bins))
