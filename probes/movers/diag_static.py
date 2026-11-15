"""Probe: what are the near-static peaks in the Haumea field? Reference brightness, Gaia."""
import logging
import sys

import numpy as np

sys.path.insert(0, "src")
from pxs.catalogs import GAIA_TAP, cached_fetch, gaia_query, parse_gaia
from pxs.movers.difference import reference_for
from pxs.movers.field import load_field

logging.basicConfig(level=logging.WARNING)
cra, cdec = 218.45 + 0, 0  # replaced below
from pxs.movers.ephem import horizons, interp_position

rows = horizons("136108", 60821, 60881, "6h")
ra, dec = interp_position(rows, 60851)
cra, cdec = ra + 3 / 60 / np.cos(np.radians(dec)), dec + 4 / 60
fd = load_field(cra, cdec, 20.0, 0)
refs = [reference_for(s, fd.refs)[0] for s in fd.search]
ref = np.nanmedian(np.stack(refs), axis=0)
img = np.nanmedian(np.stack([s.image for s in fd.search]), axis=0)
gaia = parse_gaia(cached_fetch(GAIA_TAP, gaia_query(fd.grid, cap=5000)), fd.grid)
gx, gy = fd.grid.sky_to_px([g["ra"] for g in gaia], [g["dec"] for g in gaia])
gm = np.array([g["g_mag"] or 99 for g in gaia])
print("gaia n", len(gaia))
for x, y in [(26, 106), (34, 14), (129, 191), (187, 120), (117, 193), (131, 124), (87, 27), (161, 24)]:
    d = np.hypot(gx - x - 0.5, gy - y - 0.5)
    j = np.argmin(d)
    print(x, y, "ref", round(float(ref[y, x]), 3), "img", round(float(img[y, x]), 3),
          "diff", round(float(img[y, x] - ref[y, x]), 3), "nearest gaia", round(float(d[j]), 2), gm[j])
print("sky robust sigma of ref", 1.4826 * np.nanmedian(np.abs(ref - np.nanmedian(ref))))
