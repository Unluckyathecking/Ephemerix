"""Ephemerides from the NASA/JPL Horizons API, observed from SPHEREx itself.

Horizons carries SPHEREx as spacecraft -163182 (concatenated TLEs from Space-Track), so
`CENTER='500@-163182'` gives astrometric RA/Dec as seen from the spacecraft, with its
low-Earth-orbit parallax included. Measured for Haumea at 50 au on MJD 60900.1: the
geocentric position differs from the SPHEREx one by 0.19 arcsec (0.03 SPHEREx pixel).
For a main-belt asteroid the same offset reaches several arcsec (see docs in the PR),
so the geocentre is never used here.

Network access is isolated in `_get`: one host, fixed path, bounded timeout, plain
User-Agent, retries from `pxs.spherex.net`. The Horizons COMMAND comes only from
`bodies.resolve`, which accepts a curated designation or a strict pattern. Responses are
cached on disk under <PXS_CACHE>/horizons/ keyed by the request parameters.

Units: MJD (UTC), degrees, arcsec/hour, au, degrees for angles, V magnitude.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pxs.spherex import config as spx_config
from pxs.spherex.net import check_status, session, with_retries

log = logging.getLogger(__name__)

API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
OBSERVER = "500@-163182"  # SPHEREx spacecraft
TIMEOUT_S = 60.0
TLIST_CHUNK = 80  # discrete times per request (keeps the URL short)
QUANTITIES = "1,3,9,19,20,23,24"
_MJD0 = datetime(1858, 11, 17)


class HorizonsError(RuntimeError):
    """Horizons answered with an error or a table that cannot be parsed."""


@dataclass(frozen=True)
class EphemPoint:
    """Body position seen from SPHEREx at one time.

    ra, dec: astrometric ICRF, degrees. dra_cosd, ddec: rates in arcsec/hour.
    vmag: Horizons apparent magnitude (V for asteroids, total T-mag for comets), NaN if none.
    r_au: heliocentric distance; delta_au: distance from SPHEREx. elong_deg: solar
    elongation; phase_deg: Sun-target-observer angle.
    """

    mjd: float
    ra: float
    dec: float
    dra_cosd: float
    ddec: float
    vmag: float
    r_au: float
    delta_au: float
    elong_deg: float
    phase_deg: float

    @property
    def rate_arcsec_h(self) -> float:
        return math.hypot(self.dra_cosd, self.ddec)


def cache_dir() -> Path:
    return spx_config.cache_dir().parent / "horizons"


def _get(params: dict[str, str]) -> dict:
    """One GET to the Horizons API; returns the decoded JSON. The only network call here."""

    def go() -> dict:
        r = session().get(API_URL, params=params, timeout=TIMEOUT_S)
        check_status(r, "Horizons")
        return r.json()

    return with_retries(go, "Horizons")


def _cached(params: dict[str, str]) -> str:
    """The `result` text of a Horizons request, from the disk cache when present."""
    tag = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    path = cache_dir() / f"{tag}.json"
    if path.exists():
        return json.loads(path.read_text())["result"]
    data = _get(params)
    if data.get("error") or "$$SOE" not in str(data.get("result", "")):
        msg = str(data.get("error") or data.get("result", ""))[:400]
        raise HorizonsError(f"Horizons returned no ephemeris: {msg}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"params": params, "result": data["result"]}))
    tmp.replace(path)
    return str(data["result"])


def _base(command: str) -> dict[str, str]:
    return {"format": "json", "COMMAND": f"'{command}'", "EPHEM_TYPE": "OBSERVER",
            "CENTER": f"'{OBSERVER}'", "QUANTITIES": f"'{QUANTITIES}'", "OBJ_DATA": "NO",
            "CSV_FORMAT": "YES", "ANG_FORMAT": "DEG", "EXTRA_PREC": "YES",
            "TIME_TYPE": "UT", "CAL_FORMAT": "CAL", "TIME_DIGITS": "FRACSEC"}


def _mjd(text: str) -> float:
    s = text.strip()
    for fmt in ("%Y-%b-%d %H:%M:%S.%f", "%Y-%b-%d %H:%M:%S", "%Y-%b-%d %H:%M"):
        try:
            t = datetime.strptime(s, fmt)
            return (t - _MJD0).total_seconds() / 86400.0
        except ValueError:
            continue
    raise HorizonsError(f"cannot read Horizons date {s!r}")


def _num(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan


def parse(result: str) -> list[EphemPoint]:
    """EphemPoints from a CSV observer table (QUANTITIES as above, ANG_FORMAT=DEG)."""
    lines = result.splitlines()
    try:
        soe = lines.index("$$SOE")
        eoe = lines.index("$$EOE")
    except ValueError as e:
        raise HorizonsError("no $$SOE/$$EOE block in the Horizons result") from e
    header = next(ln for ln in reversed(lines[:soe]) if ln.strip().startswith("Date"))
    cols = [c.strip() for c in header.split(",")]

    def find(*names: str) -> int:
        for n in names:
            if n in cols:
                return cols.index(n)
        raise HorizonsError(f"Horizons table lacks column {names[0]!r}")

    ix = {"ra": find("R.A._____(ICRF)", "R.A.___(ICRF)"), "dec": find("DEC_____(ICRF)",
                                                                       "DEC____(ICRF)"),
          "dra": find("dRA*cosD"), "ddec": find("d(DEC)/dt"), "r": find("r"),
          "delta": find("delta"), "elong": find("S-O-T"), "phase": find("S-T-O")}
    mag = next((cols.index(n) for n in ("APmag", "T-mag") if n in cols), None)
    out = []
    for ln in lines[soe + 1:eoe]:
        v = [c.strip() for c in ln.split(",")]
        out.append(EphemPoint(
            mjd=_mjd(v[0]), ra=float(v[ix["ra"]]), dec=float(v[ix["dec"]]),
            dra_cosd=_num(v[ix["dra"]]), ddec=_num(v[ix["ddec"]]),
            vmag=math.nan if mag is None else _num(v[mag]), r_au=_num(v[ix["r"]]),
            delta_au=_num(v[ix["delta"]]), elong_deg=_num(v[ix["elong"]]),
            phase_deg=_num(v[ix["phase"]])))
    return out


def ephemeris_range(command: str, mjd_start: float, mjd_stop: float,
                    step: str = "1d") -> list[EphemPoint]:
    """Ephemeris on a regular grid from mjd_start to mjd_stop (step in Horizons units)."""
    if not (math.isfinite(mjd_start) and math.isfinite(mjd_stop) and mjd_start < mjd_stop):
        raise ValueError(f"bad MJD range {mjd_start}..{mjd_stop}")
    params = {**_base(command), "START_TIME": f"'JD {mjd_start + 2400000.5:.5f}'",
              "STOP_TIME": f"'JD {mjd_stop + 2400000.5:.5f}'", "STEP_SIZE": f"'{step}'"}
    return parse(_cached(params))


def ephemeris_at(command: str, mjds: Sequence[float]) -> list[EphemPoint]:
    """Ephemeris at each given MJD (UTC), in the order given. Times are rounded to 1e-6 d."""
    uniq = sorted({round(float(m), 6) for m in mjds})
    by_mjd: dict[float, EphemPoint] = {}
    for i in range(0, len(uniq), TLIST_CHUNK):
        chunk = uniq[i:i + TLIST_CHUNK]
        params = {**_base(command), "TLIST_TYPE": "MJD",
                  "TLIST": " ".join(f"'{m:.6f}'" for m in chunk)}
        pts = parse(_cached(params))
        if len(pts) != len(chunk):
            raise HorizonsError(f"asked for {len(chunk)} times, got {len(pts)}")
        by_mjd.update(zip(chunk, pts))
    return [by_mjd[round(float(m), 6)] for m in mjds]
