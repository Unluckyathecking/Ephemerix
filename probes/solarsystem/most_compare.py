"""Compare the frames found along the Horizons track with IRSA MOST's list for the same body.
Run with: uv run --with astroquery python probes/solarsystem/most_compare.py 136108"""
import logging
import sys

import numpy as np
from astroquery.ipac.irsa import Most

from pxs.solarsystem import track
from pxs.solarsystem.bodies import resolve

logging.basicConfig(level=logging.WARNING)
body = resolve(sys.argv[1])
r = Most.query_object(output_mode="Regular", obj_name=body.designation, obs_begin="2025-04-01",
                      obs_end="2026-11-13", catalog="spherex")["results"]
most = {str(u).split("?")[0].split("/ibe/data/spherex/")[-1]: float(m)
        for u, m in zip(r["image_url"], r["mjd_obs"])}
mine = {v.frame.s3_key: v for v in track.find_visits(body.horizons, 61357.0).visits}
print(f"MOST {len(most)} frames, mine {len(mine)}, both {len(set(most) & set(mine))}")
only = sorted(set(most) - set(mine), key=most.get)
mjd = np.array([most[k] for k in only])
if len(mjd):
    print("MOST-only frames by month (MJD/30):", np.unique((mjd // 30).astype(int), return_counts=True))
    print("examples:", only[:3])
pm = np.array(sorted(most.values()))
print("MOST passes:", [(round(c.min()), round(c.max()), len(c))
                       for c in np.split(pm, np.where(np.diff(pm) > 20)[0] + 1)])
