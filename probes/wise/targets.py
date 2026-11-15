"""Resolve the 5 test targets via SIMBAD TAP (J2000 position, proper motion, parallax).

Uses the Harvard SIMBAD mirror: on 14 Nov 2026 simbad.cds.unistra.fr returned
404 "Page unavailable" for both sim-id and sim-tap.
"""
import json
from pathlib import Path

import numpy as np
import requests

UA = {"User-Agent": "planet-x-spherex-probe"}
TAP = "https://simbad.harvard.edu/simbad/sim-tap/sync"
NAMES = {  # key -> SIMBAD normalised identifier
    "barnard": "NAME Barnard's star",
    "epsindib": "* eps Ind B",
    "wise0855": "WISE J085510.83-071442.5",
    "rwaur": "V* RW Aur",
    "rdra": "V* R Dra",
}


CACHE = Path("cache/wise")
REF_EPOCH = 2017.0  # stamp centre = target position at this epoch (fixed for all visits)


def position_at(t: dict, year: float) -> tuple[float, float]:
    """Linear proper-motion propagation from SIMBAD's J2000 position (arcsec-level is enough)."""
    dt = year - 2000.0
    dec = t["dec"] + t["pmdec"] / 3.6e6 * dt
    ra = t["ra"] + t["pmra"] / 3.6e6 * dt / np.cos(np.radians(t["dec"]))
    return ra, dec


def load_target(key: str) -> dict:
    return json.load(open(CACHE / "targets.json"))[key]


def resolve(ident):
    q = ("SELECT b.main_id, b.ra, b.dec, b.pmra, b.pmdec, b.plx_value, b.coo_bibcode, b.pm_bibcode "
         "FROM basic b JOIN ident i ON i.oidref=b.oid WHERE i.id='%s'" % ident.replace("'", "''"))
    r = requests.get(TAP, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": q},
                     headers=UA, timeout=30)
    r.raise_for_status()
    d = r.json()
    if not d["data"]:
        raise ValueError(f"SIMBAD: no match for {ident!r}")
    cols = [c["name"] for c in d["metadata"]]
    return dict(zip(cols, d["data"][0]))


if __name__ == "__main__":
    out = {k: resolve(v) for k, v in NAMES.items()}
    print(json.dumps(out, indent=1))
    json.dump(out, open("cache/wise/targets.json", "w"), indent=1)
