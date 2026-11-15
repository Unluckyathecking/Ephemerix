"""Probe: which FLAGS bits sit on Haumea in its own frames, versus on empty sky?"""
import logging
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, "src")
from pxs.movers.ephem import horizons, interp_position
from pxs.movers.field import load_field
from pxs.spherex.config import FLAG_BITS

logging.basicConfig(level=logging.WARNING)
rows = horizons("136108", 60821, 60881, "6h")
ra, dec = interp_position(rows, 60851)
cra, cdec = ra + 3 / 60 / np.cos(np.radians(dec)), dec + 4 / 60
fd = load_field(cra, cdec, 20.0, 0)
on, off = Counter(), Counter()
for f, s in fd.search_stamps:
    x, y = s.pixel_of(*interp_position(rows, s.mjd))
    ix, iy = round(x) - s.x0, round(y) - s.y0
    core = s.flags[iy - 1:iy + 2, ix - 1:ix + 2]
    sky = s.flags[iy + 20:iy + 23, ix + 20:ix + 23]
    for name, b in FLAG_BITS.items():
        on[name] += int(np.any(core & (1 << b)))
        off[name] += int(np.any(sky & (1 << b)))
print("frames", len(fd.search_stamps))
for name in FLAG_BITS:
    if on[name] or off[name]:
        print(f"{name:12s} on-body {on[name]:3d}  sky {off[name]:3d}")
