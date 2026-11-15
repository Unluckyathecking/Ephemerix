"""Write the small recorded-data fixtures used by tests/test_astro_recorded.py.

    uv run python probes/astro/make_fixtures.py

From the stacks pickled by dump_stacks.py (our own files): 81x81 (R Dra 121x121) cutouts of saturated frames
with the Gaia + parallax position of the target, and the motion-fit epochs (mjd, ra, dec,
error) the pipeline measures for four targets. Written with Claude Code.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

from pxs import crossband
from pxs.astrometry import parallax_factors, propagate, px_to_sky
from pxs.build import _ids, _measure, _position_px
from pxs.manifest import frame_entry, motion_frames

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests" / "fixtures" / "astro"
HALF = {"barnards-star": 40, "r-draconis": 60}  # R Dra's SPHEREx hole is 60" across
CUTOUTS = {"barnards-star": ["wise-w2-2010b", "wise-w2-2020b", "wise-w2-2023a", "wise-w1-2014b",
                             "spx-b6-2026a"],
           "r-draconis": ["spx-b3-2025a"]}
MOTION = ["barnards-star", "epsilon-indi-b", "wise-0855-0714", "2mass-0415-0935"]


def load(slug: str) -> dict:
    return pickle.loads((REPO / "cache" / "astro" / f"{slug}.pkl").read_bytes())


def parallax_of(slug: str) -> float | None:
    rows = json.loads((REPO / "data" / "targets.json").read_text())
    rows = rows if isinstance(rows, list) else rows.get("targets", rows)
    return next((r.get("parallax_mas") for r in rows if r["slug"] == slug), None)


def truth_px(t, grid, mjd: float, plx: float | None) -> tuple[float, float]:
    """Gaia position at the frame epoch with parallax, in grid pixels."""
    from pxs.astrometry import decimal_year

    ra, dec = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr,
                        float(decimal_year(mjd)))
    fe, fn = (float(v) * (plx or 0.0) / 3.6e6 for v in parallax_factors(mjd, ra, dec))
    x, y = grid.sky_to_px(ra + fe / np.cos(np.radians(dec)), dec + fn)
    return float(x), float(y)


def cutouts() -> None:
    for slug, ids in CUTOUTS.items():
        d = load(slug)
        t, grid = d["target"], d["grid"]
        for fid, (band, st) in zip(_ids(d["stacks"]), d["stacks"]):
            if fid not in ids:
                continue
            x, y = _position_px(t, grid, st.mjd)
            h = HALF[slug]
            i0, j0 = int(y) - h, int(x) - h
            sl = (slice(i0, i0 + 2 * h + 1), slice(j0, j0 + 2 * h + 1))
            tx, ty = truth_px(t, grid, st.mjd, parallax_of(slug))
            mask = st.saturated_mask[sl] if st.saturated_mask is not None else None
            np.savez_compressed(
                OUT / f"{slug}-{fid}.npz", image=st.image[sl].astype(np.float32),
                saturated_mask=np.zeros(0, bool) if mask is None else mask,
                predicted=np.array([x - j0, y - i0]), truth=np.array([tx - j0, ty - i0]),
                meta=json.dumps({"mission": st.mission, "band": band, "mjd": st.mjd,
                                 "wavelength_um": st.wavelength_um,
                                 "native_pixscale_arcsec": st.native_pixscale_arcsec,
                                 "pixscale_arcsec": grid.pixscale_arcsec}))


def motion_epochs() -> None:
    out = {}
    for slug in MOTION:
        d = load(slug)
        t, grid = d["target"], d["grid"]
        frames = []
        for fid, (band, st) in zip(_ids(d["stacks"]), d["stacks"]):
            guess = _position_px(t, grid, st.mjd)
            c, notes = _measure(t, grid, st, guess, d["gaia"])
            frames.append(frame_entry(fid, band, st, f"{fid}.png", guess, c, notes))
        use = motion_frames(crossband.check(frames, grid.pixscale_arcsec))
        ra, dec = px_to_sky([f["centroid_px"][0] for f in use], [f["centroid_px"][1] for f in use],
                            grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
        out[slug] = {"published_pm_masyr": [t.pmra_masyr, t.pmdec_masyr],
                     "parallax_mas": parallax_of(slug),
                     "epochs": [{"id": f["id"], "mjd": f["mjd"], "ra": float(a), "dec": float(b),
                                 "err_arcsec": f["centroid_err_arcsec"]}
                                for f, a, b in zip(use, ra, dec)]}
    (OUT / "motion_epochs.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    cutouts()
    motion_epochs()
