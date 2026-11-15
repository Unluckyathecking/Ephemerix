"""Probe: SPHEREx passes over a field near a body at quadrature (Horizons), with frame counts."""
import sys, logging
import numpy as np
sys.path.insert(0, "src")
from pxs.movers.ephem import horizons, interp_position
from pxs.movers.frames import field_passes
logging.basicConfig(level=logging.INFO, format="%(message)s")
for num in sys.argv[1:]:
    rows = horizons(num, 60766, 61340, "1d")
    el = np.array([r.elong_deg for r in rows])
    quad = [rows[i] for i in range(1, len(rows)) if (el[i-1] - 90) * (el[i] - 90) <= 0]
    for q in quad:
        fp = field_passes(q.ra, q.dec)
        print(num, f"quad mjd {q.mjd:.1f} pos {q.ra:.4f} {q.dec:.4f} V {q.vmag} d {q.delta_au:.1f}")
        for p in fp.passes:
            dets = {d: sum(f.detector == d for f in p.frames) for d in (1, 2, 3, 4)}
            a, b = interp_position(rows, p.mjd_start), interp_position(rows, p.mjd_end)
            mv = np.hypot((b[0]-a[0])*np.cos(np.radians(a[1])), b[1]-a[1])*3600/6.15
            print(f"   pass {p.mjd_start:.1f}-{p.mjd_end:.1f} {dets} body moves {mv:.0f} px")
