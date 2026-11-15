"""Completeness figures and per-field limits for the blind search.

    uv run --with matplotlib python probes/movers/figures.py
(matplotlib is used only here, for the documentation figures.)
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, "src")
from pxs.movers.completeness import Trial, curve
from pxs.movers.geometry import D_MAX_AU, pass_geometry
from pxs.movers.inject import Synthetic
from pxs.movers.limits import V_OVER_1UM, distance_curves, motion_distance, statement, vmag_from_1um
from pxs.movers.search import MIN_MOTION_PX

CAMPAIGN = Path("cache/movers/campaign")
IMG = Path("docs/validation/img")
IMG.mkdir(parents=True, exist_ok=True)
summary = {}
fig, ax = plt.subplots(figsize=(7, 4.2))
fig2, ax2 = plt.subplots(figsize=(7, 4.2))
all_trials = []
for p in sorted(CAMPAIGN.glob("*.npz")):
    if p.stem.startswith("test_"):
        continue
    z = np.load(p)
    meta = json.loads((CAMPAIGN / f"{p.stem}.json").read_text())
    trials = [Trial(Synthetic(0, 0, d, r, 0, f), r, bool(k), s, np.nan) for f, r, d, k, s in
              zip(z["inj_flux"], z["inj_rate"], z["inj_d"], z["inj_rec"], z["inj_snr"])]
    all_trials += trials
    c = curve(trials, n_bins=8)
    f50, f90 = c.flux_at(0.5) * 1e3, c.flux_at(0.9) * 1e3
    mjd = np.linspace(*meta["pass_mjd"], 40)
    geom = pass_geometry(meta["ra"], meta["dec"], mjd, 6.15)
    dmot = min(motion_distance(geom, MIN_MOTION_PX), D_MAX_AU)
    v50 = vmag_from_1um(f50)
    summary[p.stem] = dict(
        n_injected=len(trials), n_recovered=int(sum(t.recovered for t in trials)),
        flux50_ujy=f50, flux90_ujy=f90, vmag50=v50, vmag90=vmag_from_1um(f90),
        d_motion_au=dmot, statement=statement(v50, dmot),
        distances=distance_curves(v50, dmot), extras_per_run=z["extras"].tolist(),
        real_ge7=meta["real_ge7"], null_ge7=meta["null_ge7"], n_frames=meta["n_frames"],
        n_ref=meta["n_ref"], read_s=meta["read_s"], search_s=meta["search_s"],
        masked=meta["masked"], n_trials=meta["n_trials"], total_s=meta["total_s"],
        center=[meta["ra"], meta["dec"]], pass_mjd=meta["pass_mjd"])
    ok = np.isfinite(c.completeness)
    ax.plot(c.flux_mjy[ok] * 1e3, c.completeness[ok], marker="o", ms=3, label=p.stem)
for lo, hi, lab in ((0, 1, "< 1 px/day"), (1, 3, "1-3 px/day"), (3, 6, "3-6 px/day"),
                    (6, 99, "> 6 px/day")):
    c = curve(all_trials, n_bins=8, rate_range=(lo, hi))
    ok = np.isfinite(c.completeness) if c.n.size else np.array([], bool)
    if ok.any():
        ax2.plot(c.flux_mjy[ok] * 1e3, c.completeness[ok], marker="o", ms=3,
                 label=f"{lab} (n={int(c.n.sum())})")
for a, title in ((ax, "Completeness per field (S/N >= 7, one pass)"),
                 (ax2, "Completeness by rate, all fields")):
    a.set_xscale("log")
    a.set_xlabel("flux at 1 um (uJy), solar-coloured mover")
    a.set_ylabel("fraction recovered")
    a.axhline(0.5, color="grey", lw=0.5)
    a.axhline(0.9, color="grey", lw=0.5, ls=":")
    top = a.secondary_xaxis("top", functions=(lambda f: np.array([vmag_from_1um(x) if x > 0
                                                                  else np.nan for x in
                                                                  np.atleast_1d(f)]),
                                              lambda v: 10 ** ((23.9 - v) / 2.5) / V_OVER_1UM))
    top.set_xlabel("V")
    a.set_title(title, fontsize=10)
    a.legend(fontsize=7)
fig.tight_layout()
fig.savefig(IMG / "movers-completeness.png", dpi=130)
fig2.tight_layout()
fig2.savefig(IMG / "movers-completeness-rate.png", dpi=130)
Path("cache/movers/limits_summary.json").write_text(json.dumps(summary, indent=1, default=float))
print(json.dumps({k: {kk: v[kk] for kk in ("vmag50", "vmag90", "flux50_ujy", "n_injected",
                                           "real_ge7", "null_ge7", "d_motion_au")}
                  for k, v in summary.items()}, indent=1, default=float))
