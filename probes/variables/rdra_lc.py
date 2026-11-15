"""R Dra: relative brightness from the unsaturated PSF wings (9-13 px ring), every collection, vs time.

Same ring as probes/spherex/rdra_var.py (outside every saturation footprint). Background from r >= 13.5 px.
Writes cache/variables/lc/r-dra-wing.json.
"""
import json, logging
from pathlib import Path
import numpy as np
from pxs.spherex import config
from pxs.spherex.net import BlockStore
from pxs.spherex.photometry import good_mask, radius
from pxs.spherex.query import find_frames
from pxs.spherex.stamps import read_many
from lightcurve import subsample, ALL, STORE_ROOT, OUT

RA, DEC = 248.16761, 66.75498


def wing(s, r_in=9.0, r_out=13.0, r_bkg=13.5, min_good=0.9):
    img = s.image - s.zodi
    good = good_mask(s)
    r = radius(s, s.xpix, s.ypix)
    bk, ring, full = good & (r >= r_bkg), good & (r >= r_in) & (r < r_out), (r >= r_in) & (r < r_out)
    if bk.sum() < 20 or ring.sum() < min_good * full.sum():
        return np.nan, np.nan
    bkg = np.median(img[bk])
    return float(np.mean(img[ring]) - bkg), float(np.sqrt(np.mean(s.variance[ring]) / ring.sum()))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:  # control star: name ra dec
        NAME, RA, DEC = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    else:
        NAME = "r-dra"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    frames = find_frames(RA, DEC, collections=ALL)
    by = {c: sum(f.collection == c for f in frames) for c in ALL}
    use = subsample(frames, 400)
    logging.info("R Dra %s reading %d", by, len(use))
    b = read_many([(f, RA, DEC) for f in use], 17, with_psf=False, store=BlockStore(root=STORE_ROOT), workers=8)
    rows = []
    for f, s in b.stamps:
        fl, er = wing(s)
        rows.append({"mjd": s.mjd, "det": s.detector, "wl": s.wave_um, "coll": f.collection, "wing": fl, "err": er})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{NAME}-wing.json").write_text(json.dumps({"frames_by_collection": by, "n_read": len(use), "rows": rows}))
    print("done", by, len(rows), sum(np.isfinite(r["wing"]) for r in rows))
