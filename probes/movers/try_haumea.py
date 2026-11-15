"""Probe: first end-to-end run of the search on a field near Haumea (pass MJD 60846-60856)."""
import logging
import sys
import time

import numpy as np

sys.path.insert(0, "src")
from pxs.movers.difference import difference_cube
from pxs.movers.ephem import horizons, interp_position
from pxs.movers.field import load_field
from pxs.movers.geometry import pass_geometry, trajectory_grid
from pxs.movers.matched import planes, reflected_template
from pxs.movers.search import make_trials, run_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
body, mjd_mid, dra, ddec = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
rows = horizons(body, mjd_mid - 30, mjd_mid + 30, "6h")
ra, dec = interp_position(rows, mjd_mid)
cra, cdec = ra + dra / 60 / np.cos(np.radians(dec)), dec + ddec / 60
fd = None
from pxs.movers.frames import field_passes, pass_containing
from pxs.movers.field import usable_passes
pidx = usable_passes(field_passes(cra, cdec)).index(
    field_passes(cra, cdec).passes[pass_containing(field_passes(cra, cdec), mjd_mid)])
fd = load_field(cra, cdec, 20.0, pidx)
cube = difference_cube(fd.search, fd.refs)
cube = cube.with_template(reflected_template(cube.wave_um))
print("frames", len(cube), "masked", round(cube.masked_fraction, 3), "waves", cube.wave_um.min(), cube.wave_um.max())
pl = planes(cube)
print("noise scales", np.round(pl.noise_scale, 2))
geom = pass_geometry(cra, cdec, cube.mjd, fd.grid.pixscale_arcsec)
tg = trajectory_grid(geom)
tr = make_trials(geom, tg)
print("trajectories", len(tg), "unique", len(tr), "dv", tg.dv_px_day, "reflex/50au", geom.reflex_px_day / 50)
t = time.time()
m = run_search(pl, tr)
print("search s", time.time() - t)
# where is the body?
x, y = fd.grid.sky_to_px(*interp_position(rows, geom.t0))
xa, ya = fd.grid.sky_to_px(*interp_position(rows, cube.mjd.min()))
xb, yb = fd.grid.sky_to_px(*interp_position(rows, cube.mjd.max()))
print("body at t0 px", x, y, "rate px/day", (xb - xa) / np.ptp(cube.mjd), (yb - ya) / np.ptp(cube.mjd))
order = np.argsort(m.best_snr.ravel())[::-1][:15]
for o in order:
    yy, xx = divmod(o, m.best_snr.shape[1])
    j = tr.rep[m.best_trial[yy, xx]]
    print(f"peak {xx} {yy} snr {m.best_snr[yy, xx]:.1f} d {tg.d_au[j]:.0f} v {tg.vx[j]:.2f} {tg.vy[j]:.2f}")
np.savez("cache/movers/haumea_try.npz", snr=m.best_snr, idx=m.best_trial)
