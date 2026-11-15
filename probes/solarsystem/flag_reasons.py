"""Why are some exposures of a body flagged? Reasons and which FLAGS bits sit in the PSF core.
Uses the stamp cache from a previous run.  uv run python probes/solarsystem/flag_reasons.py 136108"""
import collections
import sys

import numpy as np

from pxs.solarsystem.bodies import resolve
from pxs.solarsystem.phot import measure_pass, read_visits
from pxs.solarsystem.stacks import read_half
from pxs.solarsystem.track import find_visits, passes_of
from pxs.spherex import config
from pxs.spherex.photometry import radius

body = resolve(sys.argv[1])
tr = find_visits(body.horizons, 61357.0)
names = {v: k for k, v in config.FLAG_BITS.items()}
for pas, vs in passes_of(tr.visits):
    if len(vs) < 6:
        continue
    read, _ = read_visits(vs, read_half())
    ms = measure_pass(read)
    reasons = collections.Counter((m.point.detector, m.point.reason) for m in ms if m.point.flagged)
    bits = collections.Counter()
    for m in ms:
        if not m.point.flagged:
            continue
        s = m.stamp
        core = radius(s, s.xpix, s.ypix) <= config.R_FIT
        f = int(np.bitwise_or.reduce(s.flags[core]))
        bits.update(names[b] for b in range(32) if f & (1 << b) and b in names)
    print(f"pass {pas.mjd_start:.0f}: flagged {sum(reasons.values())}/{len(ms)}", dict(reasons))
    print("   bits in core of flagged frames:", dict(bits))
