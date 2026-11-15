"""Write the recorded-data fixtures of tests/test_astro_pairfit.py and test_astro_trackfit.py.

    uv run python probes/astro/dump_stacks.py cwise-1055-5443 cwise-0411-4714
    uv run python probes/astro/make_motion_fixtures.py

- cwise-1055-5443-wise-w2-2021a-field.npz: one whole W2 visit (240x240), for planted pairs.
- cwise-0411-4714-w2-visits.npz: the 22 W2 visits of CWISE J0411+4714, 61x61 px around its
  track, background-subtracted exactly as trackmotion.measure hands them to trackfit.fit,
  with the seed, catalogue velocity and neighbour positions it uses.

Written with Claude Code.
"""

from __future__ import annotations

import json
import math

import numpy as np
from stacks import load, w2_visits

from pxs import centroid, trackmotion
from pxs.astrometry import propagate
from pxs.build import REPO, _ids

OUT = REPO / "tests" / "fixtures" / "astro"
HALF = 30


def field(slug: str = "cwise-1055-5443", fid: str = "wise-w2-2021a") -> None:
    d, _, _ = load(slug)
    band, st = next(s for f, s in zip(_ids(d["stacks"]), d["stacks"]) if f == fid)
    meta = {"mission": st.mission, "band": band, "mjd": st.mjd,
            "wavelength_um": st.wavelength_um,
            "native_pixscale_arcsec": st.native_pixscale_arcsec,
            "pixscale_arcsec": d["grid"].pixscale_arcsec}
    np.savez_compressed(OUT / f"{slug}-{fid}-field.npz", image=st.image.astype(np.float32),
                        meta=json.dumps(meta))


def visits(slug: str = "cwise-0411-4714") -> None:
    d, _, catwise = load(slug)
    t, grid = d["target"], d["grid"]
    pix = grid.pixscale_arcsec
    use, prep, years = w2_visits(d)
    ra, dec = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, float(years.mean()))
    seed = tuple(float(v) for v in grid.sky_to_px(ra, dec))
    v = (-t.pmra_masyr / 1000 / pix, -t.pmdec_masyr / 1000 / pix)
    half = centroid._fit_half_width_px(prep[0].sigma_px)
    reach = half + prep[0].fwhm_px + 0.5 * math.hypot(*v) * float(np.ptp(years))
    static = trackmotion._neighbours(t, catwise, grid, float(years.mean()), seed, reach)
    i0, j0 = int(seed[1]) - HALF, int(seed[0]) - HALF
    sl = (slice(i0, i0 + 2 * HALF + 1), slice(j0, j0 + 2 * HALF + 1))
    if not all(f.usable[sl].all() for f in prep):
        raise SystemExit("unusable pixels in the cutout: the fixture assumes none")
    np.savez_compressed(
        OUT / f"{slug}-w2-visits.npz",
        resid=np.array([f.resid[sl] for f in prep]).astype(np.float16),
        noise=np.array([f.noise for f in prep]), years=years,
        seed=np.array([seed[0] - j0, seed[1] - i0]), velocity=np.array(v),
        static=np.array([(x - j0, y - i0) for x, y in static]),
        sigma_px=prep[0].sigma_px, inflate=use[0].native_pixscale_arcsec / pix, half=half)


if __name__ == "__main__":
    field()
    visits()
