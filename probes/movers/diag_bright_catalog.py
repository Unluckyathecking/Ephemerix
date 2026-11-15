"""Probe: cache Gaia DR3 (ESA TAP) and 2MASS (CDS VizieR TAP) for the diag_bright fields.

    uv run python probes/movers/diag_bright_catalog.py
Returns per field a dict with grid-pixel x, y and G, J, K magnitudes (load()).
"""
from __future__ import annotations

import csv
import io

import numpy as np

from pxs.catalogs import GAIA_TAP, cached_fetch, gaia_query
from pxs.movers.layers import field_grid

FIELDS = {"Haumea": (218.64096674077047, 15.037436666666666), "B5": (230.0, -10.0),
          "B6": (140.0, 25.0), "BarnardsStar": (269.4461566, 4.7696437),
          "WISE0855": (133.7583173, -7.2419772)}
EPOCH = 2025.7  # campaign passes: MJD 60846-60994
VIZIER_TAP ="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"


def tmass_query(ra: float, dec: float, radius: float = 0.24, cap: int = 3000) -> str:
    return (f'SELECT TOP {cap} RAJ2000, DEJ2000, Jmag, Hmag, Kmag FROM "II/246/out" '
            f"WHERE 1=CONTAINS(POINT('ICRS', RAJ2000, DEJ2000), "
            f"CIRCLE('ICRS', {ra}, {dec}, {radius})) ORDER BY Jmag ASC")


def _num(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def load(name: str, with_2mass: bool = False) -> dict[str, dict[str, np.ndarray]]:
    ra, dec = FIELDS[name]
    g = field_grid(ra, dec, 20.0)
    gaia = list(csv.DictReader(io.StringIO(cached_fetch(GAIA_TAP, gaia_query(g, cap=3000)))))
    tm = []  # VizieR and IRSA were both unreachable on 15 Nov 2026; 2MASS is optional
    if with_2mass:
        try:
            tm = list(csv.DictReader(io.StringIO(cached_fetch(VIZIER_TAP,
                                                              tmass_query(ra, dec)))))
        except Exception:  # noqa: BLE001
            tm = []
    # Propagated from 2016.0 to the passes' epoch (~2025.7) by proper motion: Barnard's Star
    # moves 10"/yr, 15 px over that interval.
    dt = EPOCH - 2016.0
    pm = [(np.nan_to_num(_num(r["pmra"])), np.nan_to_num(_num(r["pmdec"]))) for r in gaia]
    gdec = [_num(r["dec"]) + p[1] * dt / 3.6e6 for r, p in zip(gaia, pm)]
    gra = [_num(r["ra"]) + p[0] * dt / 3.6e6 / np.cos(np.radians(d)) for r, p, d in
           zip(gaia, pm, gdec)]
    gx, gy = g.sky_to_px(gra, gdec)
    tx, ty = (g.sky_to_px([_num(r["RAJ2000"]) for r in tm], [_num(r["DEJ2000"]) for r in tm])
              if tm else (np.zeros(0), np.zeros(0)))
    return {"gaia": {"x": np.asarray(gx) - 0.5, "y": np.asarray(gy) - 0.5,
                     "g": np.array([_num(r["phot_g_mean_mag"]) for r in gaia])},
            "tmass": {"x": np.asarray(tx) - 0.5, "y": np.asarray(ty) - 0.5,
                      "j": np.array([_num(r["Jmag"]) for r in tm]),
                      "k": np.array([_num(r["Kmag"]) for r in tm])}}


if __name__ == "__main__":
    for n in FIELDS:
        c = load(n)
        print(n, "gaia", len(c["gaia"]["g"]), "2mass", len(c["tmass"]["j"]),
              "J<8:", int(np.sum(c["tmass"]["j"] < 8)), "J<10:", int(np.sum(c["tmass"]["j"] < 10)))
