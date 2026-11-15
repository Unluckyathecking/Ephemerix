"""Which solar elongations do SPHEREx frames containing a body actually have?
Runs the track search with a wide window and histograms the frames found."""
import logging
import sys
import time

import numpy as np

from pxs.solarsystem import track
from pxs.solarsystem.bodies import resolve

logging.basicConfig(level=logging.WARNING)
body = resolve(sys.argv[1])
t0 = time.time()
track.ELONG_WINDOW_DEG = (40.0, 140.0)
tr = track.find_visits(body.horizons, 61350.0); v = tr.visits; print("cones", tr.n_cones, "failed", tr.failed_cones)
print(f"{body.name}: {len(v)} candidate frames in {time.time()-t0:.0f}s")
el = np.array([x.eph.elong_deg for x in v])
print("elongation of candidate frames: min %.1f max %.1f" % (el.min(), el.max()))
print(np.histogram(el, bins=np.arange(40, 145, 5)))
for p, vs in track.passes_of(v):
    e = [x.eph.elong_deg for x in vs]
    print(f"pass {p.mjd_start:.1f}-{p.mjd_end:.1f}: {len(vs)} frames, elong {min(e):.1f}-{max(e):.1f}")
