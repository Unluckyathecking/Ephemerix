"""How long a pass the trajectory model (pxs.movers.geometry) holds for.

A straight-line barycentric body (exact gnomonic projection, distance varying) is compared
with the search model v dt + curve/d at its mid-pass distance, after fitting the free start
and rate. Prints the worst residual (px) over random bound velocities at 30-100 au, per field,
epoch and span. Result (Nov 2026): <= 0.35 px up to 16 days, ~0.5 px at 20, 1-2.5 px at
28-44 days; this sets pxs.movers.field.MAX_SPAN_DAYS. Light, runs in seconds.

    uv run python probes/movers/model_span.py
"""

from __future__ import annotations

import numpy as np

from pxs.movers.geometry import (AU_PER_DAY_CIRC_1AU, RAD_PER_ARCSEC, SPEED_FACTOR,
                                 earth_posvel, pass_geometry, tangent_basis)
from pxs.spherex import config

FIELDS = {"Haumea": (218.64, 15.04, 60846.6), "B7": (10.0, -15.0, 60700.0),
          "B1": (160.0, 10.0, 60700.0), "Eris": (27.44, -0.17, 60900.0)}


def worst_error(ra: float, dec: float, t0: float, span: float, rng: np.random.Generator) -> float:
    ps = config.PIXSCALE_ARCSEC
    mjd = np.linspace(t0 - span / 2, t0 + span / 2, 41)
    g = pass_geometry(ra, dec, mjd, ps, t0)
    n, east, north = tangent_basis(ra, dec)
    earth, _ = earth_posvel(mjd)
    e0, _ = earth_posvel(np.array([t0]))
    a = np.column_stack([np.ones_like(g.dt), g.dt])
    worst = 0.0
    for d in (30.0, 50.0, 100.0):
        for _ in range(20):
            u = rng.normal(size=3)
            u *= SPEED_FACTOR * AU_PER_DAY_CIRC_1AU / np.sqrt(d) * rng.uniform() / np.linalg.norm(u)
            r = (e0[:, 0] + d * n)[:, None] + u[:, None] * g.dt - earth
            off = np.vstack([-(east @ r), -(north @ r)]) / (n @ r) / (ps * RAD_PER_ARCSEC)
            res = off - g.curve_px / d
            res -= (a @ np.linalg.lstsq(a, res.T, rcond=None)[0]).T
            worst = max(worst, float(np.max(np.hypot(*res))))
    return worst


def main() -> None:
    rng = np.random.default_rng(0)
    for name, (ra, dec, m0) in FIELDS.items():
        for dt0 in (0, 60, 120):
            errs = [f"{s} d: {worst_error(ra, dec, m0 + dt0, s, rng):.2f}"
                    for s in (9, 14, 16, 20, 28, 44)]
            print(f"{name} +{dt0} d  " + "  ".join(errs))


if __name__ == "__main__":
    main()
