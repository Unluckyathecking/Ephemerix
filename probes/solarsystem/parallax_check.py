"""How wrong is a geocentric ephemeris for SPHEREx? Horizons from the geocentre (500@399)
against Horizons from SPHEREx (500@-163182), over one 98-minute orbit, for a TNO and a
main-belt asteroid.

    uv run python probes/solarsystem/parallax_check.py
"""
import math

import numpy as np

from pxs.solarsystem import horizons

MJDS = list(61060.0 + np.arange(0, 100, 5) / 1440.0)  # every 5 min over 100 min
for name, cmd in [("Haumea", "136108;"), ("Eris", "136199;"), ("(24) Themis", "24;"),
                  ("(1) Ceres", "1;")]:
    sp = horizons.ephemeris_at(cmd, MJDS)
    orig = horizons.OBSERVER
    horizons.OBSERVER = "500@399"
    try:
        geo = horizons.ephemeris_at(cmd, MJDS)
    finally:
        horizons.OBSERVER = orig
    d = [math.hypot((a.ra - b.ra) * math.cos(math.radians(a.dec)), a.dec - b.dec) * 3600
         for a, b in zip(sp, geo)]
    print(f"{name:12s} delta {sp[0].delta_au:6.2f} au: geocentric - SPHEREx offset "
          f"max {max(d):6.2f}\" ({max(d) / 6.15:.2f} px), mean {np.mean(d):5.2f}\"; "
          f"rate {sp[0].rate_arcsec_h:.1f}\"/h")
