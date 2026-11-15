"""RW Aur: wing brightness (same 9-13 px ring as R Dra) per all-sky pass, per detector, at matched wavelength.

Each pass steps through every wavelength, so an exposure's template (same detector, within wl/60) holds the
same wavelength from the other passes: a change between passes is a change in time, not in colour.
Usage (from probes/variables): uv run python rwaur_wing.py rw-aur control-2m0507a control-2m0507b
"""
import json
import sys

import numpy as np

from analysis import LC, bin_epochs, relative, robust_std


def per_pass(name: str) -> dict:
    rows = json.loads((LC / f"{name}-wing.json").read_text())["rows"]
    a = {k: np.array([np.nan if r[k] is None else r[k] for r in rows], float) for k in ("mjd", "det", "wl", "wing")}
    rel, _ = relative(a["wl"], a["det"], a["wing"], np.ones(len(rows)), frac=1 / 60, min_n=3)
    out = {}
    for k in range(1, 7):
        s = (a["det"] == k) & np.isfinite(rel)
        if s.sum() >= 5:
            out[k] = {"scatter": robust_std(rel[s]),
                      "passes": bin_epochs(a["mjd"][s], rel[s], np.full(s.sum(), 0.05), gap=20, min_n=3)}
    return {"a": a, "rel": rel, "det": out}


RW_AUR = (76.95653, 30.40144)
# 2MASS 05072728+3022599, Ks 6.37 (AAA), 5 arcmin from RW Aur: bright enough to saturate like RW Aur.
# IRSA's SIA was down on 15 Nov, so it is measured in RW Aur's own frames (cached frame list).
BRIGHT_CONTROL = ("control-2m0507bright", 76.863669, 30.383331)


def measure_control() -> None:
    """Wing photometry of the bright control in RW Aur's frames (same subsample as rdra_lc for RW Aur)."""
    from lightcurve import ALL, STORE_ROOT, subsample
    from pxs.spherex.net import BlockStore
    from pxs.spherex.query import find_frames
    from pxs.spherex.stamps import read_many
    from rdra_lc import wing

    name, ra, dec = BRIGHT_CONTROL
    use = subsample(find_frames(*RW_AUR, collections=ALL), 400)
    b = read_many([(f, ra, dec) for f in use], 17, with_psf=False, store=BlockStore(root=STORE_ROOT), workers=8)
    rows = []
    for f, s in b.stamps:
        fl, er = wing(s)
        rows.append({"mjd": s.mjd, "det": s.detector, "wl": s.wave_um, "coll": f.collection, "wing": fl, "err": er})
    (LC / f"{name}-wing.json").write_text(json.dumps({"n_read": len(use), "rows": rows}))


if __name__ == "__main__":
    if sys.argv[1] == "--measure-control":
        measure_control()
        sys.exit()
    for n in sys.argv[1:]:
        r = per_pass(n)
        print("==", n, "finite", int(np.isfinite(r["rel"]).sum()))
        for k, d in r["det"].items():
            print(f" D{k} scatter {d['scatter']:.3f}: " + "  ".join(f"{t:.0f}:{v:.3f}±{e:.3f}(n{m})" for t, v, e, m, *_ in d["passes"]))
