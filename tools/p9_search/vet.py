"""Catalogue checks for every real peak above its field's null maximum (run locally).

For each such peak: JPL Small-Body Identification at mid-pass (V < 25, matched within
MATCH_ARCSEC), and Gaia DR3 and CatWISE2020 sources within MATCH_ARCSEC. Each catalogue is
tried at several TAP services in turn (NOIRLab Astro Data Lab, then the ESA Gaia archive or
IRSA): on 15 Nov 2026 IRSA's TAP timed out, the CDS VizieR host was unavailable, the CfA
mirror returned no CatWISE rows and Data Lab came and went. Writes tools/p9_search/vetting.json,
keyed "<tile>#<rank>"; report.py folds it in. A service that fails is recorded as such,
never as "no match".

    PYTHONPATH=tools uv run python -m p9_search.vet
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import requests

from pxs.movers.ephem import known_objects

from .report import UNITS, VETTING, load_units, survivors

DATALAB = "https://datalab.noirlab.edu/tap/sync"
ESA_GAIA = "https://gea.esac.esa.int/tap-server/tap/sync"
IRSA = "https://irsa.ipac.caltech.edu/TAP/sync"
MATCH_ARCSEC = 60.0  # about 10 SPHEREx pixels: wide enough for a bright star's wings
PIXEL_ARCSEC = 6.15
CATALOGS = {  # catalogue: (magnitude columns, [(service, table, ra column, dec column)])
    "gaia_dr3": (("phot_g_mean_mag",), [(DATALAB, "gaia_dr3.gaia_source", "ra", "dec"),
                                        (ESA_GAIA, "gaiadr3.gaia_source", "ra", "dec")]),
    "catwise2020": (("w1mpro", "w2mpro"), [(DATALAB, "catwise2020.main", "ra", "dec"),
                                           (IRSA, "catwise_2020", "ra_pm", "dec_pm")]),
}


def sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Small-angle separation (arcsec); fine below a degree."""
    dra = (ra1 - ra2 + 180.0) % 360.0 - 180.0
    return math.hypot(dra * math.cos(math.radians(0.5 * (dec1 + dec2))), dec1 - dec2) * 3600


def cone_query(service: str, table: str, rac: str, decc: str, mags: tuple[str, ...],
               ra: float, dec: float, radius_arcsec: float = MATCH_ARCSEC) -> str:
    """ADQL cone search; Data Lab needs its q3c function, the others take CONTAINS."""
    cols = f"{rac} AS ra, {decc} AS dec, {', '.join(mags)}"
    r = radius_arcsec / 3600
    if service == DATALAB:
        where = f"'t' = q3c_radial_query({rac}, {decc}, {ra:.6f}, {dec:.6f}, {r:.6f})"
    else:
        where = (f"1 = CONTAINS(POINT('ICRS', {rac}, {decc}), "
                 f"CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {r:.6f}))")
    return f"SELECT TOP 500 {cols} FROM {table} WHERE {where}"


def tap_rows(service: str, adql: str) -> list[dict[str, str]]:
    r = requests.post(service, timeout=90, headers={"User-Agent": "planet-x-spherex"},
                      data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                            "QUERY": adql})
    r.raise_for_status()
    if r.text.lstrip().startswith("<"):
        raise RuntimeError(f"TAP error: {r.text[:300]}")
    return list(csv.DictReader(io.StringIO(r.text)))


def _float(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def nearest_sources(rows: list[dict[str, str]], ra: float, dec: float,
                    mags: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        r, d = _float(row.get("ra")), _float(row.get("dec"))
        if r is None or d is None:
            continue
        s = sep_arcsec(ra, dec, r, d)
        out.append({"sep_arcsec": round(s, 1), "sep_px": round(s / PIXEL_ARCSEC, 2)}
                   | {m: _float(row.get(m)) for m in mags})
    return sorted(out, key=lambda x: x["sep_arcsec"])


def vet_peak(peak: dict, mjd_mid: float) -> dict[str, Any]:
    ra, dec = peak["ra"], peak["dec"]
    out: dict[str, Any] = {"match_arcsec": MATCH_ARCSEC}
    try:
        objs = known_objects(ra, dec, 0.02, mjd_mid, vmag_lim=25.0)
        out["jpl"] = [{"name": o.name, "vmag": o.vmag,
                       "sep_arcsec": round(sep_arcsec(ra, dec, o.ra, o.dec), 1),
                       "rate_arcsec_h": math.hypot(o.ra_rate_arcsec_h, o.dec_rate_arcsec_h)}
                      for o in objs if sep_arcsec(ra, dec, o.ra, o.dec) <= MATCH_ARCSEC]
    except Exception as e:  # noqa: BLE001 - record the failure, never "no match"
        out["jpl"] = f"failed: {type(e).__name__}: {e}"
    for key, (mags, services) in CATALOGS.items():
        errors = []
        for service, table, rac, decc in services:
            try:
                rows = tap_rows(service, cone_query(service, table, rac, decc, mags, ra, dec))
                out[key] = nearest_sources(rows, ra, dec, mags)[:5]
                out[f"{key}_service"] = service
                break
            except Exception as e:  # noqa: BLE001 - try the next service
                errors.append(f"{service}: {type(e).__name__}: {str(e)[:150]}")
        else:
            out[key] = "failed: " + " | ".join(errors)
    return out


def main(units: Path = UNITS) -> None:
    res = {}
    for name, u in load_units(units).items():
        b = u["base"]
        mid = 0.5 * (b["pass_mjd"][0] + b["pass_mjd"][1])
        for p in survivors(b):
            key = f"{name}#{p['rank']}"
            res[key] = vet_peak(p, mid) | {"mjd_mid": mid}
            print(key, round(p["snr"], 1), json.dumps(res[key])[:400])
    VETTING.write_text(json.dumps(res, indent=1) + "\n")
    print(f"{len(res)} peaks vetted -> {VETTING}")


if __name__ == "__main__":
    main()
