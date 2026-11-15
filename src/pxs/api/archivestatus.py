"""Are the outside archives answering? One light request per archive, run in parallel.

Each probe is the cheapest real request to the service the pipeline uses (the URLs come from
the pipeline's own modules). It is one plain request with a short timeout and no retry, and
deliberately not the pipeline's helpers: those hold the IRSA slots, trip the breakers, retry
and cache, so a probe through them would measure our own queue and change the pipeline.

`run_probes()` gives one record per archive: `status` "up", "slow" or "down", `latency_ms`,
and a short `detail` on failure (an HTTP status or an error class, never a body or a URL).
Only the scheduled `archive_watch` job in deploy/modal_app.py runs it, every 5 minutes; the
results are kept by `pxs.archivehistory`, which serves them without probing anything.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from pxs import catalogs
from pxs.api import bodies, resolve
from pxs.movers import ephem
from pxs.spherex import config as spherex_config
from pxs.wise import net as wise_net

SLOW_S = 5.0  # an answer slower than this is "slow"; IRSA is often a few seconds
TIMEOUT_S = (5.0, 10.0)  # connect, read; no answer within these is "down"
USER_AGENT = catalogs.USER_AGENT


@dataclass(frozen=True)
class Archive:
    id: str
    name: str
    used_for: str  # what may be missing when it is down, as a noun phrase
    method: str  # "GET", "POST" or "HEAD"
    url: str
    params: Mapping[str, str] | None = None
    backup: bool = False  # a mirror: its failure alone loses nothing
    tap: bool = False  # TAP errors come back as HTTP 200 VOTables


def _tap(adql: str) -> dict[str, str]:
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}


ARCHIVES: tuple[Archive, ...] = (
    Archive("irsa_sia", "NASA IRSA image search", "WISE and SPHEREx images", "GET",
            spherex_config.SIA_URL,
            {"COLLECTION": "spherex_qr3", "POS": "CIRCLE 10 10 0.0001", "MAXREC": "1",
             "RESPONSEFORMAT": "CSV"}),
    Archive("irsa_tap", "NASA IRSA catalogue service", "CatWISE sources and WISE frame checks",
            "POST", catalogs.IRSA_TAP, _tap("SELECT TOP 1 table_name FROM TAP_SCHEMA.tables"),
            tap=True),
    Archive("wise_s3", "WISE images on AWS", "WISE images", "HEAD", wise_net.BUCKET_URL),
    Archive("spherex_s3", "SPHEREx images on AWS", "SPHEREx images", "HEAD",
            spherex_config.BUCKET_URL),
    Archive("gaia", "ESA Gaia archive", "Gaia stars", "POST", catalogs.GAIA_TAP,
            _tap("SELECT TOP 1 table_name FROM tap_schema.tables"), tap=True),
    Archive("datalab", "NOIRLab Astro Data Lab", "backup copies of Gaia and CatWISE", "POST",
            catalogs.DATALAB_TAP, _tap("SELECT TOP 1 table_name FROM tap_schema.tables"),
            backup=True, tap=True),
    Archive("sesame", "CDS Sesame name lookup", "object name lookups", "GET",
            f"{resolve.SESAME_URL}?Vega"),
    Archive("horizons", "JPL Horizons", "Solar System body positions", "GET",
            ephem.HORIZONS_URL,
            {"format": "json", "COMMAND": "'499'", "OBJ_DATA": "NO", "MAKE_EPHEM": "NO"}),
    Archive("sbdb", "JPL Small-Body Database", "Solar System body name lookups", "GET",
            bodies.SBDB_URL, {"sstr": "1"}),
)

Request = Callable[[Archive], requests.Response]


def http_request(a: Archive) -> requests.Response:
    """The one request for `a`: no retry, no cache, the project User-Agent."""
    data = a.params if a.method == "POST" else None
    params = a.params if a.method == "GET" else None
    return requests.request(a.method, a.url, params=params, data=data, timeout=TIMEOUT_S,
                            headers={"User-Agent": USER_AGENT}, allow_redirects=True)


def classify(a: Archive, request: Request = http_request,
             clock: Callable[[], float] = time.monotonic) -> dict:
    """Run one probe and say what happened. Never raises."""
    start = clock()
    detail = None
    try:
        res = request(a)
        if not 200 <= res.status_code < 300 and not (a.method == "HEAD" and res.status_code == 403):
            detail = f"HTTP {res.status_code}"
        elif a.tap and res.text.lstrip().startswith("<"):
            detail = "error answer"
    except requests.ConnectTimeout:  # before ConnectionError: it is both
        detail = f"could not connect within {int(TIMEOUT_S[0])} s"
    except requests.Timeout:
        detail = f"no answer within {int(TIMEOUT_S[1])} s"
    except requests.ConnectionError:
        detail = "could not connect"
    except Exception as exc:  # noqa: BLE001 - a probe must never break the page
        detail = type(exc).__name__
    seconds = clock() - start
    status = "down" if detail else ("slow" if seconds > SLOW_S else "up")
    return {"id": a.id, "name": a.name, "used_for": a.used_for, "backup": a.backup,
            "status": status, "latency_ms": None if detail else round(seconds * 1000),
            "detail": detail}


def run_probes(archives: Sequence[Archive] = ARCHIVES, request: Request = http_request) -> list[dict]:
    """Every probe at once; results in the order of `archives`."""
    with ThreadPoolExecutor(max_workers=len(archives)) as pool:
        return list(pool.map(lambda a: classify(a, request), archives))


