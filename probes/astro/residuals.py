"""Per-epoch residuals of the target from its catalogue track, and the fitted motion, using
the pipeline's own centroid on the stacks pickled by dump_stacks.py.

    uv run python probes/astro/residuals.py <slug> [...] [--json out.json]

Residuals are measured minus predicted, (east, north) in arcsec. Written with Claude Code.
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np

from pxs import crossband
from pxs.astrometry import fit_motion, propagate, px_to_sky
from pxs.build import _ids, _measure, _position_px
from pxs.manifest import frame_entry, measured_motion, motion_frames

log = logging.getLogger("residuals")
REPO = Path(__file__).resolve().parents[2]


def parallax_factors(mjd, ra, dec):
    """Same as pxs.astrometry.parallax_factors, copied so the probe also runs on old code."""
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time

    x, y, z = get_body_barycentric("earth", Time(mjd, format="mjd")).xyz.to_value("au")
    a, d = np.radians(ra), np.radians(dec)
    return (x * np.sin(a) - y * np.cos(a),
            x * np.cos(a) * np.sin(d) + y * np.sin(a) * np.sin(d) - z * np.cos(d))


def parallax_of(slug: str) -> float | None:
    rows = json.loads((REPO / "data" / "targets.json").read_text())
    rows = rows if isinstance(rows, list) else rows.get("targets", rows)
    return next((r.get("parallax_mas") for r in rows if r["slug"] == slug), None)


def motion_with_parallax(frames: list[dict], grid, plx: float | None) -> dict | None:
    """What manifest.measured_motion gives once it passes the target's parallax."""
    use = motion_frames(frames)
    if len(use) < 2:
        return None
    ra, dec = px_to_sky([f["centroid_px"][0] for f in use], [f["centroid_px"][1] for f in use],
                        grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
    try:
        return fit_motion([f["mjd"] for f in use], ra, dec,
                          [f["centroid_err_arcsec"] for f in use], parallax_mas=plx)
    except TypeError:  # code before fit_motion took a parallax
        return None


def run(slug: str) -> dict:
    # Our own pickles from dump_stacks.py, so unpickling them is safe.
    d = pickle.loads((REPO / "cache" / "astro" / f"{slug}.pkl").read_bytes())
    plx = parallax_of(slug)
    t, grid, stacks, gaia = d["target"], d["grid"], d["stacks"], d["gaia"]
    frames = []
    for fid, (band, st) in zip(_ids(stacks), stacks):
        guess = _position_px(t, grid, st.mjd)
        c, notes = _measure(t, grid, st, guess, gaia)
        frames.append(frame_entry(fid, band, st, f"{fid}.png", guess, c, notes))
    frames = crossband.check(frames, grid.pixscale_arcsec)
    s = grid.pixscale_arcsec
    rows = []
    for f in frames:
        r = None
        if f["centroid_px"]:
            ra, dec = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, 2020.0)
            fe, fn = (float(v) * (plx or 0.0) / 1000.0
                      for v in parallax_factors(f["mjd"], ra, dec))
            r = [round(-(f["centroid_px"][0] - f["predicted_px"][0]) * s - fe, 3),
                 round(-(f["centroid_px"][1] - f["predicted_px"][1]) * s - fn, 3)]
        rows.append({"id": f["id"], "band": f["band"], "mjd": f["mjd"], "res_en": r,
                     "err": f["centroid_err_arcsec"], "warnings": f["warnings"]})
    return {"slug": slug, "pm_pub": [t.pmra_masyr, t.pmdec_masyr], "parallax_mas": plx,
            "motion_as_shipped": measured_motion(frames, grid),
            "motion": motion_with_parallax(frames, grid, plx), "rows": rows}


def show(r: dict) -> None:
    print(f"== {r['slug']} published {r['pm_pub']} (residuals: parallax removed)")
    for row in r["rows"]:
        if row["band"] in ("W2", "W1", "spx-b6"):
            res = row["res_en"]
            txt = "-" if res is None else f"{res[0]:+7.2f} {res[1]:+7.2f} ±{row['err']:.2f}"
            print(f"  {row['id']:18s} {txt:28s} {'; '.join(row['warnings'])[:90]}")
    w2 = np.array([row["res_en"] for row in r["rows"] if row["band"] == "W2" and row["res_en"]])
    if len(w2):
        print(f"  W2 residual mean {w2.mean(0).round(2)} rms {w2.std(0).round(2)} "
              f"max |r| {np.hypot(*w2.T).max():.2f} arcsec")
    for key in ("motion_as_shipped", "motion"):
        mm = r[key]
        if not mm:
            continue
        dpm = np.array([mm["pmra_masyr"] - r["pm_pub"][0], mm["pmdec_masyr"] - r["pm_pub"][1]])
        ax = np.array([mm.get("err_pmra_masyr", mm["err_masyr"]),
                       mm.get("err_pmdec_masyr", mm["err_masyr"])])
        print(f"  {key}: {mm}\n    measured-published {dpm.round(1)} mas/yr = "
              f"{(dpm / ax).round(2)} sigma per axis")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        out = Path(args[args.index("--json") + 1])
        args = args[:args.index("--json")]
    res = [run(a) for a in args]
    for r in res:
        show(r)
    if out:
        out.write_text(json.dumps(res, indent=1))

