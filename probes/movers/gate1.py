"""Gate 1: blind search of fields near Haumea, Makemake and Eris; compare with Horizons."""
import json
import logging
import sys

import numpy as np

sys.path.insert(0, "src")
from pxs.movers.core import THRESHOLD, rate_of, run_core
from pxs.movers.ephem import horizons, interp_position
from pxs.movers.field import load_field, usable_passes
from pxs.movers.frames import field_passes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
FIELDS = {"Haumea": ("136108", 60851.0, 3, 4), "Makemake": ("136472", 61200.0, -4, 3),
          "Eris": ("136199", 60873.7, 4, -3)}
out = {}
for name in sys.argv[1:]:
    num, mid, dra, ddec = FIELDS[name]
    rows = horizons(num, mid - 30, mid + 30, "6h")
    ra, dec = interp_position(rows, mid)
    cra, cdec = ra + dra / 60 / np.cos(np.radians(dec)), dec + ddec / 60
    passes = usable_passes(field_passes(cra, cdec))
    pidx = [i for i, p in enumerate(passes) if p.mjd_start - 3 <= mid <= p.mjd_end + 3][0]
    fd = load_field(cra, cdec, 20.0, pidx)
    core = run_core(fd.search, fd.refs, cra, cdec, fd.grid.pixscale_arcsec)
    g = core.geom
    x, y = fd.grid.sky_to_px(*interp_position(rows, g.t0))
    (xa, ya), (xb, yb) = (fd.grid.sky_to_px(*interp_position(rows, m))
                          for m in (core.cube.mjd.min(), core.cube.mjd.max()))
    span = np.ptp(core.cube.mjd)
    mrow = rows[len(rows) // 2]
    true = dict(x=float(x) - 0.5, y=float(y) - 0.5, vx=float((xb - xa) / span),
                vy=float((yb - ya) / span), vmag=mrow.vmag, delta=mrow.delta_au)
    rec = []
    for d in core.above(5.0)[:10]:
        vx, vy, dd = rate_of(core, d)
        rec.append(dict(x=d.x, y=d.y, snr=round(d.snr, 1), raw=round(d.snr_raw, 1),
                        flux_ujy=round(d.flux_mjy * 1e3, 1), err_ujy=round(d.flux_err_mjy * 1e3, 1),
                        vx=round(vx, 2), vy=round(vy, 2), d=round(dd), h1=round(d.snr_first, 1),
                        h2=round(d.snr_second, 1), share=round(d.max_frame_share, 2),
                        nclip=d.n_clipped, nfr=d.n_frames))
    out[name] = dict(centre=[cra, cdec], pass_mjd=[core.cube.mjd.min(), core.cube.mjd.max()],
                     n_frames=len(core.cube), n_ref=len(fd.refs), read_s=fd.read_seconds,
                     search_s=core.maps.seconds, trials=len(core.trials),
                     masked=core.cube.masked_fraction, truth=true,
                     n_above7=len(core.above(THRESHOLD)),
                     n_null_above7=len(core.above(THRESHOLD, null=True)),
                     null_top=[round(d.snr, 1) for d in core.null_detections[:5]], top=rec)
    print(json.dumps(out[name], indent=1, default=float))
with open(f"cache/movers/gate1_{'_'.join(sys.argv[1:])}.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)
