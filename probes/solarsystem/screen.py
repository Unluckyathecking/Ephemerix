"""Screen candidate bodies cheaply: predicted V, distance, rate and Galactic latitude on the
days SPHEREx can see them (Horizons, observer SPHEREx), before any photometry.

    uv run python probes/solarsystem/screen.py
"""
import logging
import sys

import numpy as np
from astropy.coordinates import SkyCoord

from pxs.solarsystem.horizons import ephemeris_range
from pxs.solarsystem.track import SURVEY_START_MJD, visible

logging.basicConfig(level=logging.WARNING)
CANDIDATES = [
    ("Pluto+Charon (barycentre)", "9"), ("Gonggong", "225088;"), ("Quaoar", "50000;"),
    ("Orcus", "90482;"), ("Sedna", "90377;"), ("Varuna", "20000;"), ("Ixion", "28978;"),
    ("Salacia", "120347;"), ("Chiron", "2060;"), ("Chariklo", "10199;"),
    ("Haumea", "136108;"), ("Makemake", "136472;"), ("Eris", "136199;"),
]
SMALL = [
    ("3I/ATLAS", "DES=C/2025 N1;CAP;NOFRAG"), ("(24) Themis", "24;"), ("(65) Cybele", "65;"),
    ("(52) Europa", "52;"), ("(153) Hilda", "153;"), ("(10) Hygiea", "10;"),
]
for name, cmd in SMALL if "small" in sys.argv else CANDIDATES:
    try:
        vis = visible(ephemeris_range(cmd, SURVEY_START_MJD, 61357.0, "1d"))
    except Exception as e:  # noqa: BLE001
        print(f"{name:28s} Horizons failed: {e}")
        continue
    if not vis:
        print(f"{name:28s} never at SPHEREx elongation")
        continue
    v = np.array([e.vmag for e in vis])
    b = SkyCoord([e.ra for e in vis], [e.dec for e in vis], unit="deg").galactic.b.deg
    rate = np.array([e.rate_arcsec_h for e in vis])
    print(f"{name:28s} V {np.nanmin(v):5.1f}-{np.nanmax(v):5.1f}  r {vis[0].r_au:5.1f} au  "
          f"|b| {np.min(np.abs(b)):4.1f}-{np.max(np.abs(b)):4.1f}  rate {rate.min():.2f}-"
          f"{rate.max():.2f}\"/h  days {len(vis)}")
