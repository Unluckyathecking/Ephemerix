"""Minimal JPL calls for validation and known-object matching, with plain `requests`.

`horizons(...)`: geocentric ephemeris of one body (positions for validating recoveries).
`known_objects(...)`: JPL Small-Body Identification of catalogued bodies in a field.
Both are cached on disk under cache/movers/jpl/ by a hash of the request. The observer is
geocentric: SPHEREx's 700 km orbit adds at most 7000 km / 30 au = 0.3" of parallax.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

from .paths import cache_root

log = logging.getLogger(__name__)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
SBIDENT_URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
USER_AGENT = "planet-x-spherex"
TIMEOUT_S = 60.0
MJD_TO_JD = 2400000.5


@dataclass(frozen=True)
class EphemRow:
    """One ephemeris line: MJD (UT), RA/Dec (deg, ICRF astrometric), V mag, r and delta (au),
    Sun-observer-target elongation (deg)."""

    mjd: float
    ra: float
    dec: float
    vmag: float
    r_au: float
    delta_au: float
    elong_deg: float


@dataclass(frozen=True)
class KnownObject:
    """A catalogued small body in a field at one epoch. Rates in arcsec/hour."""

    name: str
    ra: float
    dec: float
    vmag: float
    ra_rate_arcsec_h: float
    dec_rate_arcsec_h: float


def _cached_get(url: str, params: dict[str, str]) -> str:
    tag = hashlib.sha1(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    path: Path = cache_root() / "jpl" / f"{tag}.json"
    if path.exists():
        return path.read_text()
    r = requests.get(url, params=params, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text)
    return r.text


def _float(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return math.nan


def parse_horizons(text: str) -> list[EphemRow]:
    """Rows of a Horizons CSV observer table with QUANTITIES 1,9,19,20,23 in degrees."""
    result = json.loads(text)["result"]
    if "$$SOE" not in result:
        raise ValueError(f"Horizons returned no ephemeris: {result[:300]}")
    body = result.split("$$SOE")[1].split("$$EOE")[0]
    out = []
    for line in body.strip().splitlines():
        c = [x.strip() for x in line.split(",")]
        jd = _float(c[0]) if c[0].replace(".", "").isdigit() else math.nan
        out.append(EphemRow(mjd=jd - MJD_TO_JD, ra=float(c[3]), dec=float(c[4]),
                            vmag=_float(c[5]), r_au=_float(c[7]), delta_au=_float(c[9]),
                            elong_deg=_float(c[11])))
    return out


def horizons(command: str, mjd_start: float, mjd_stop: float, step: str = "1d") -> list[EphemRow]:
    """Geocentric ephemeris of `command` (e.g. "136199" for Eris) between two MJDs."""
    params = {
        "format": "json", "COMMAND": f"'{command}'", "EPHEM_TYPE": "OBSERVER",
        "CENTER": "'500@399'", "START_TIME": f"'JD{mjd_start + MJD_TO_JD:.5f}'",
        "STOP_TIME": f"'JD{mjd_stop + MJD_TO_JD:.5f}'", "STEP_SIZE": f"'{step}'",
        "QUANTITIES": "'1,9,19,20,23'", "CSV_FORMAT": "YES", "ANG_FORMAT": "DEG",
        "TIME_TYPE": "UT", "CAL_FORMAT": "JD",
    }
    return parse_horizons(_cached_get(HORIZONS_URL, params))


def interp_position(rows: list[EphemRow], mjd: float) -> tuple[float, float]:
    """Linearly interpolated (ra, dec) in degrees at an MJD inside the table."""
    t = np.array([r.mjd for r in rows])
    ra = np.unwrap(np.radians([r.ra for r in rows]))
    dec = np.array([r.dec for r in rows])
    return float(np.degrees(np.interp(mjd, t, ra)) % 360.0), float(np.interp(mjd, t, dec))


def _sexa(deg: float, hours: bool) -> str:
    v = deg / 15.0 if hours else deg
    sign = "-" if v < 0 else ""
    v = abs(v)
    a = int(v)
    b = int((v - a) * 60)
    c = (v - a - b / 60) * 3600
    return f"{sign}{a:02d}-{b:02d}-{c:05.2f}"


def parse_sbident(text: str) -> list[KnownObject]:
    """Objects of a JPL sb_ident JSON response (first-pass list)."""
    d = json.loads(text)
    fields = d.get("fields_first") or []
    out = []
    for row in d.get("data_first_pass") or []:
        rec = dict(zip(fields, row))
        ra_h = [float(x) for x in rec["Astrometric RA (hh:mm:ss)"].split(":")]
        dec_s = rec["Astrometric Dec (dd mm'ss\")"].replace("'", " ").replace('"', "").split()
        sign = -1.0 if dec_s[0].startswith("-") else 1.0
        dd = [abs(float(x)) for x in dec_s]
        out.append(KnownObject(
            name=rec["Object name"],
            ra=15.0 * (ra_h[0] + ra_h[1] / 60 + ra_h[2] / 3600),
            dec=sign * (dd[0] + dd[1] / 60 + dd[2] / 3600),
            vmag=_float(rec["Visual magnitude (V)"]),
            ra_rate_arcsec_h=_float(rec["RA rate (\"/h)"]),
            dec_rate_arcsec_h=_float(rec["Dec rate (\"/h)"])))
    return out


def known_objects(ra: float, dec: float, half_width_deg: float, mjd: float,
                  vmag_lim: float = 21.0) -> list[KnownObject]:
    """Catalogued asteroids and comets in a square field at an MJD (geocentric)."""
    jd = mjd + MJD_TO_JD
    params = {
        "sb-kind": "a", "mpc-code": "500", "obs-time": f"{jd:.5f}",
        "fov-ra-center": _sexa(ra, True), "fov-dec-center": _sexa(dec, False),
        "fov-ra-hwidth": f"{half_width_deg:.4f}", "fov-dec-hwidth": f"{half_width_deg:.4f}",
        "vmag-lim": f"{vmag_lim:.1f}",
    }
    return parse_sbident(_cached_get(SBIDENT_URL, params))
