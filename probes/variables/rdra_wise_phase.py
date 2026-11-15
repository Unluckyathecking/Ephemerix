"""Do R Dra's NEOWISE per-visit medians follow its VSX ephemeris (P=246.12 d, max JD 2457370.0)?"""
import numpy as np
from wise_brief import get
P, T0 = 246.12, 2457370.0 - 2400000.5
for t in get("R Dra"):
    if t["table"][0] != "neowiser_p1bs_psd": continue
    m = np.asarray(t["mjd"], float); o = np.argsort(m); m = m[o]
    w1 = np.asarray(t["w1mpro"], float)[o]; w2 = np.asarray(t["w2mpro"], float)[o]
    g = np.split(np.arange(len(m)), np.where(np.diff(m) > 30)[0] + 1)
    mm = np.array([m[i].mean() for i in g]); a1 = np.array([np.nanmedian(w1[i]) for i in g]); a2 = np.array([np.nanmedian(w2[i]) for i in g])
    ph = ((mm - T0) / P) % 1
    c = np.cos(2 * np.pi * ph)  # +1 at maximum
    for band, a in (("W1", a1), ("W2", a2)):
        r = np.corrcoef(c, a)[0, 1]
        A = np.c_[np.ones_like(c), c, np.sin(2*np.pi*ph)]; coef, *_ = np.linalg.lstsq(A, a, rcond=None)
        res = a - A @ coef
        print(f"{band}: corr(cos phase, mag) = {r:+.2f}  (negative = brighter at max); fitted semi-amp {np.hypot(*coef[1:]):.2f} mag, residual rms {res.std():.2f}")
    for x, p, b1, b2 in zip(mm, ph, a1, a2): print(f"  {x:.0f} phase {p:.2f}  W1 {b1:.2f}  W2 {b2:.2f}")
print("SPHEREx windows: phase of 2025-06-09 = %.2f, 2025-06-29 = %.2f, 2026-06-19 = %.2f" % tuple(((np.array([60835, 60855, 61210]) - T0) / P) % 1))
