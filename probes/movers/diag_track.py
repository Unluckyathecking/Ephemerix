"""Probe: per-frame flux along Haumea's track (true ephemeris positions)."""
import logging
import sys

import numpy as np

sys.path.insert(0, "src")
from pxs.movers.core import prepare
from pxs.movers.ephem import horizons, interp_position
from pxs.movers.field import load_field
from pxs.spherex.config import MJYSR_TO_MJY

logging.basicConfig(level=logging.WARNING)
rows = horizons("136108", 60821, 60881, "6h")
ra, dec = interp_position(rows, 60851)
cra, cdec = ra + 3 / 60 / np.cos(np.radians(dec)), dec + 4 / 60
fd = load_field(cra, cdec, 20.0, 0)
cube, pl, geom = prepare(fd.search, fd.refs, cra, cdec, fd.grid.pixscale_arcsec)
for i in np.argsort(cube.mjd):
    x, y = fd.grid.sky_to_px(*interp_position(rows, cube.mjd[i]))
    xi, yi = int(x), int(y)
    p, q = pl.psi[i, yi, xi], pl.phi[i, yi, xi]
    raw = cube.diff[i, yi - 1:yi + 2, xi - 1:xi + 2]
    img = fd.search[i].image[yi, xi]
    f = p / q * MJYSR_TO_MJY / cube.template[i] if q > 0 else np.nan
    print(f"{cube.mjd[i]:.2f} D{cube.detector[i]} {cube.wave_um[i]:.3f} t{cube.template[i]:.2f} "
          f"s{pl.noise_scale[i]:.2f} phi>0 {q > 0} flux_mJy {f:.3f} snr {p/np.sqrt(q) if q>0 else 0:.1f} "
          f"diffmax {np.nanmax(raw) if np.isfinite(raw).any() else np.nan:.3f} img {img:.3f} nan3x3 {np.isnan(raw).sum()}")
