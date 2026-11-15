"""Trajectory-grid hole: replay the test_haumea injection run (seed, 25 movers) and show,
per source, the best detection near it, then the match() outcome. Run before and after the
trajectory_grid fix: 11/25 recovered before, 15/25 after.
    uv run python probes/movers/diag_grid_hole.py
"""
import logging
import math
import sys

import numpy as np

sys.path.insert(0, "src")
from pxs.movers.candidates import track_xy
from pxs.movers.completeness import MATCH_PX, injected_track, match
from pxs.movers.core import THRESHOLD, rate_of, run_core
from pxs.movers.field import load_field, search_layers
from pxs.movers.inject import draw_sources, injector
from pxs.movers.matched import reflected_template

logging.basicConfig(level=logging.WARNING)
ra, dec = 218.64096674077047, 15.037436666666666
fd = load_field(ra, dec, 20.0, 0)
base = run_core(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec, with_null=False)
rng = np.random.default_rng(sum(map(ord, "test_haumea")))
srcs = draw_sources(rng, 25, fd.grid, base.geom, (0.02, 0.4), (30.0, 1000.0))
layers = search_layers(fd, injector(srcs, base.geom, fd.grid, reflected_template))
core = run_core(layers, fd.refs, ra, dec, fd.grid.pixscale_arcsec, with_null=False,
                tgrid=base.tgrid)
dets = core.above(THRESHOLD)
tg = base.tgrid
print("tgrid d range", tg.d_au.min(), tg.d_au.max(), "n", len(tg.d_au))
for s in sorted(srcs, key=lambda s: s.flux_mjy):
    truth = injected_track(s, core)
    best = None
    for d in core.detections:
        sep = math.hypot(d.x - s.x, d.y - s.y)
        close = np.mean(np.hypot(*(track_xy(core.trials, d) - truth)) <= MATCH_PX)
        if sep < 6 and (best is None or d.snr > best[0].snr):
            best = (d, sep, close)
    rate = math.hypot(s.vx, s.vy)
    span = np.max(np.hypot(truth[0] - truth[0].mean(), truth[1] - truth[1].mean()))
    msg = f"{s.flux_mjy*1e3:6.1f}uJy d={s.d_au:5.0f} v=({s.vx:5.2f},{s.vy:5.2f}) r={rate:4.2f}"
    msg += f" xy=({s.x:5.1f},{s.y:5.1f}) span={span:4.1f}"
    if best:
        d, sep, close = best
        vx, vy, dd = rate_of(core, d)
        msg += (f" | det snr={d.snr:5.1f} raw={d.snr_raw:5.1f} sep={sep:3.1f} close={close:.2f}"
                f" v=({vx:5.2f},{vy:5.2f}) d={dd:4.0f} nclip={d.n_clipped}/{d.n_frames}")
    else:
        msg += " | none within 6 px"
    print(msg)
print("extras:")
for d in dets:
    dist = min(np.min(np.hypot(*(track_xy(core.trials, d) - injected_track(s, core))))
               for s in srcs)
    near = min(math.hypot(d.x - s.x, d.y - s.y) for s in srcs)
    print(f" det ({d.x},{d.y}) snr {d.snr:.1f} start-sep {near:.1f} min track dist {dist:.1f}")
got, extra = match(srcs, core)
print("trials", len(core.trials), "search s", round(core.maps.seconds, 1))
print("recovered", sum(t.recovered for t in got), "at_position", sum(t.at_position for t in got),
      "of", len(got), "extras", [(d.x, d.y, round(d.snr, 1)) for d in extra])
