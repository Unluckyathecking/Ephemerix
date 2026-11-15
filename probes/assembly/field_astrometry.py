"""Measured minus Gaia-predicted positions of field stars in each frame of a built view.

    uv run python probes/assembly/field_astrometry.py <view dir> [gmax]

A systematic offset shared by field stars means a grid or pixel-convention error; an
offset seen only on the target means target astrometry. Centroids are measured on the
8-bit PNG (a monotonic stretch does not move a symmetric peak). Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from pxs import centroid
from pxs.astrometry import decimal_year, propagate, sky_to_px
from pxs.grid import Stack


def main(view: Path, gmax: float) -> None:
    m = json.loads((view / "manifest.json").read_text())
    stars = [s for s in m["overlays"]["gaia"] if s["g_mag"] is not None and s["g_mag"] < gmax]
    c, fov, size = m["center"], m["fov_arcsec"], m["size_px"]
    scale = fov / size
    pooled: dict[str, list] = {}
    for f in m["frames"]:
        img = np.asarray(Image.open(view / f["image"]), dtype=np.float32)
        st = Stack(image=img, mission=f["mission"], band=f["band"],
                   wavelength_um=tuple(f["wavelength_um"]), mjd=f["mjd"], date_span_days=0.0,
                   n_exposures=1, native_pixscale_arcsec=f["native_pixscale_arcsec"])
        yr = float(decimal_year(f["mjd"]))
        d = []
        for s in stars:
            ra, dec = propagate(s["ra"], s["dec"], s["epoch"], s["pmra_masyr"] or 0.0,
                                s["pmdec_masyr"] or 0.0, yr)
            x, y = sky_to_px(ra, dec, c["ra"], c["dec"], fov, size)
            if not (20 < x < size - 20 and 20 < y < size - 20):
                continue
            meas = centroid.measure(st, (float(x), float(y)), scale, 4.0)
            if meas is not None and meas.snr > 5:
                d.append((meas.x - x, meas.y - y))
        if d:
            a = np.array(d)
            pooled.setdefault(f["band"], []).extend(d)
            if "-v" in sys.argv:
                print(f"{f['id']}: n={len(a)} median dx {np.median(a[:, 0]):+.2f} dy "
                      f"{np.median(a[:, 1]):+.2f} px (scatter {np.std(a, axis=0).round(2)})")
    for band, d in sorted(pooled.items()):
        a = np.array(d) * scale
        err = np.std(a, axis=0) / np.sqrt(len(a))
        print(f"{band}: n={len(a)} mean offset E {-a[:, 0].mean():+.2f} N {-a[:, 1].mean():+.2f} "
              f"arcsec (+- {err.round(2)})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 16.0)
