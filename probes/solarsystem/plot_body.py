"""Reflectance plot with ice-band windows, plus a text summary, from a body manifest.

    uv run --with matplotlib python probes/solarsystem/plot_body.py <manifest.json> <out.png>
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

m = json.loads(Path(sys.argv[1]).read_text())
ss = m["solar_system"]
name = m["target"]["name"]
for p in ss["passes"]:
    c = p["control"]
    bands = {b["band"]: b for b in p["bands"]}
    ctl = {b["band"]: b for b in (c["bands"] if c else [])}
    print(f"{name} pass {p['id']} {p['date_start'][:10]}..{p['date_end'][:10]} "
          f"frames {p['n_measured']}/{p['n_frames']} detected={p['detected']} best={p['best_band']} "
          f"S/N={p['best_snr']}")
    for b in bands:
        x, k = bands[b], ctl.get(b, {})
        print(f"   {b}: n={x['n']:3d} body-control {x['flux_ujy']} +- {x['err_ujy']} uJy "
              f"(S/N {x['snr']}); control {k.get('flux_ujy')} +- {k.get('err_ujy')} (n={k.get('n')})")
for r in ss["reflectance"]:
    print(f"reflectance {r['spectrum_id']}: {r['reading']}")
    for d in r["band_depths"]:
        print(f"   {d['label']}: depth {d['depth']} +- {d['err']} ({d['sigma']} sigma), "
              f"n_band {d['n_band']}")
print("timings", ss["timings_s"])

refl = ss["reflectance"]
if not refl:
    sys.exit(0)
r = next((x for x in refl if x["spectrum_id"] == "all-detected"), refl[0])
pts = r["points"]
w = np.array([p["wl_um"] for p in pts])
y = np.array([p["refl"] for p in pts])
e = np.array([p["err"] for p in pts])
fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
for d in r["band_depths"]:
    lo, hi = d["wl_um"]
    col = "#4a90d9" if "(H2O" in d["label"] else "#d98a4a"
    ax.axvspan(lo, hi, color=col, alpha=0.18, lw=0)
    ax.text((lo + hi) / 2, 1.0, d["label"].replace(" um", ""), rotation=90, ha="center",
            va="top", fontsize=7, color=col, transform=ax.get_xaxis_transform())
ax.axvspan(*r["norm_window_um"], color="0.85", alpha=0.5, lw=0)
ax.errorbar(w, y, e, fmt=".", ms=3, lw=0.6, color="0.35", alpha=0.5, label="single exposures")
edges = 0.75 * (1 + 1 / 20) ** np.arange(0, 60)
idx = np.digitize(w, edges)
bx, by, be = [], [], []
for i in np.unique(idx):
    s = idx == i
    if s.sum() < 2:
        continue
    wt = 1 / e[s] ** 2
    bx.append(np.average(w[s], weights=wt))
    by.append(np.sum(wt * y[s]) / wt.sum())
    be.append(1 / np.sqrt(wt.sum()))
ax.errorbar(bx, by, be, fmt="o", ms=5, color="k", label="binned (R~20)")
ax.axhline(1, color="0.5", lw=0.5, ls="--")
ax.set_xlim(0.72, 5.05)
lo, hi = np.nanpercentile(y, [2, 98])
ax.set_ylim(max(-1.2, min(-0.2, lo)), max(1.6, min(hi, 3)))
ax.set_xlabel("wavelength (um)")
ax.set_ylabel("relative reflectance (0.75-1.3 um = 1)")
ax.set_title(f"{name}: SPHEREx reflectance ({r['spectrum_id']}, control-subtracted)")
ax.legend(fontsize=8, loc="upper right")
fig.tight_layout()
fig.savefig(sys.argv[2])
print("wrote", sys.argv[2])
