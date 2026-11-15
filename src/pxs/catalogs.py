"""Gaia DR3 and CatWISE2020 sources inside a view, in the manifest's `overlays` shape.

Positions are degrees at the catalogue epoch (Gaia DR3: 2016.0; CatWISE2020 motion-fit
position ra_pm, dec_pm: MJD 57170 = 2015.405). Proper motion in mas/yr with cos dec
included. CatWISE pmra/pmdec are arcsec/yr and already projected (checked against Gaia
at dec -75), so they are only multiplied by 1000. CatWISE motions of very fast movers are
unreliable (Epsilon Indi B: 0.9"/yr against 4.7"/yr in Gaia).

Network access is one small function per service (`tap_csv`), cached on disk under
cache/catalogs/ by a hash of the request. A failed query gives an empty list and a warning.
Each catalogue has a fallback mirror, NOIRLab Astro Data Lab (`gaia_dr3.gaia_source`,
`catwise2020.main`: same columns and units, checked 15 Nov 2026 at UGPS 0722), asked only when
the primary fails or has not answered within FALLBACK_AFTER_S; the first answer is used.
Both queries run at once and the build waits for them at most OVERLAY_BUDGET_S: an answer
that is later than that is left out of this view (with the same warning) but still lands in
the cache, so a retry has it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, wait
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import nullcontext
from pathlib import Path

import requests

from pxs.astrometry import decimal_year, sky_to_px
from pxs.concurrency import background, breaker, irsa_slot, unreachable
from pxs.grid import Grid

log = logging.getLogger(__name__)

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
DATALAB_TAP = "https://datalab.noirlab.edu/tap/sync"
CACHE_DIR = Path(__file__).resolve().parents[2] / "cache" / "catalogs"
USER_AGENT = "planet-x-spherex/0.0.1 (NASA Space Apps 2026)"
MAX_SOURCES = 200
# One attempt, no retry. The build waits OVERLAY_BUDGET_S for both queries together; a
# query still running then finishes in the background (at most TIMEOUT_S; 20 s timed out in
# production) and is cached for the next build.
TIMEOUT_S = 45
OVERLAY_BUDGET_S = 10.0
FALLBACK_AFTER_S = 4.0  # Data Lab answered in about 1.7 s from the UK
GAIA_EPOCH = 2016.0
CATWISE_EPOCH = round(float(decimal_year(57170.0)), 3)

BREAKERS = {IRSA_TAP: breaker("irsa"), GAIA_TAP: breaker("gaia")}

Fetch = Callable[[str, str], str]  # (tap_url, adql) -> CSV text


def tap_csv(url: str, adql: str) -> str:
    """Run one synchronous TAP query and return the CSV body. Raises on HTTP errors.

    Queries to IRSA hold one of the process-wide IRSA slots (`concurrency.irsa_slot`). A call
    to ESA or IRSA that times out or cannot connect trips that service's breaker, and an
    answer closes it; the breaker never skips a query, it only makes `overlays` ask the Data
    Lab mirror (the same rows) at once instead of after FALLBACK_AFTER_S."""
    data = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}
    guard = BREAKERS.get(url)
    slot = irsa_slot if url == IRSA_TAP else nullcontext
    with slot():
        try:
            resp = requests.post(url, data=data, headers={"User-Agent": USER_AGENT},
                                 timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if guard is not None and unreachable(exc):
                guard.trip()
            raise
    resp.raise_for_status()
    if guard is not None:
        guard.reset()
    if resp.text.lstrip().startswith("<"):  # TAP errors come back as HTTP 200 VOTables
        raise ValueError(f"TAP query failed at {url}: {resp.text[:300]}")
    return resp.text


def cached_fetch(url: str, adql: str, fetch: Fetch = tap_csv, cache_dir: Path = CACHE_DIR) -> str:
    """`fetch` with an on-disk cache keyed by the request. Only successes are cached."""
    key = hashlib.sha256(f"{url}\n{adql}".encode()).hexdigest()[:32]
    path = cache_dir / f"{key}.csv"
    if path.exists():
        return path.read_text()
    text = fetch(url, adql)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def _radius_deg(grid: Grid) -> float:
    return grid.fov_arcsec / 3600.0 / math.sqrt(2.0) + 0.002  # field corners plus padding


def gaia_query(grid: Grid, cap: int = MAX_SOURCES) -> str:
    return (
        f"SELECT TOP {cap} source_id, ra, dec, pmra, pmdec, phot_g_mean_mag, parallax, "
        "parallax_error "
        "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"{_cone(grid)}) ORDER BY phot_g_mean_mag ASC"
    )


def catwise_query(grid: Grid, cap: int = MAX_SOURCES) -> str:
    # Constrained on the indexed ra, dec; the radius is padded so ra_pm, dec_pm still fit.
    return (
        f"SELECT TOP {cap} source_name, ra_pm, dec_pm, pmra, pmdec, w1mpro, w2mpro "
        "FROM catwise_2020 WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"{_cone(grid)}) ORDER BY w2mpro ASC"
    )


def _cone(grid: Grid) -> str:
    return (f"CIRCLE('ICRS', {grid.center_ra:.7f}, {grid.center_dec:.7f}, "
            f"{_radius_deg(grid):.5f})")


def datalab_query(adql: str, grid: Grid) -> str:
    """The same query for Data Lab, whose ADQL lacks CONTAINS: a Q3C cone instead."""
    q3c = (f"'t'=Q3C_RADIAL_QUERY(ra, dec, {grid.center_ra:.7f}, {grid.center_dec:.7f}, "
           f"{_radius_deg(grid):.5f})")
    out = adql.replace(f"1=CONTAINS(POINT('ICRS', ra, dec), {_cone(grid)})", q3c)
    out = out.replace("FROM gaiadr3.gaia_source", "FROM gaia_dr3.gaia_source")
    return out.replace("FROM catwise_2020", "FROM catwise2020.main")


def first_answer(calls: Sequence[Callable[[], str]], after_s: float = FALLBACK_AFTER_S) -> str:
    """The first successful result of `calls`, each started only when every earlier one has
    failed or `after_s` has passed since the last start. Raises the last error if all fail."""
    pending: set[Future] = set()
    errors: list[BaseException] = []
    started = 0
    while True:
        if started < len(calls):
            pending.add(background(calls[started]))
            started += 1
        if not pending:
            raise errors[-1]
        done, _ = wait(pending, timeout=after_s if started < len(calls) else None,
                       return_when=FIRST_COMPLETED)
        for fut in done:
            pending.discard(fut)
            if fut.exception() is None:
                return fut.result()
            errors.append(fut.exception())
            log.info("catalogue query failed (%s); trying the next source", fut.exception())


def _f(row: dict, key: str, scale: float = 1.0) -> float | None:
    v = (row.get(key) or "").strip()
    try:
        x = float(v) * scale
    except ValueError:
        return None
    return round(x, 7) if math.isfinite(x) else None


def _in_field(grid: Grid, ra: float, dec: float) -> bool:
    x, y = sky_to_px(ra, dec, grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
    return 0.0 <= float(x) < grid.size_px and 0.0 <= float(y) < grid.size_px


def parse_gaia(text: str, grid: Grid) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        ra, dec = _f(row, "ra"), _f(row, "dec")
        if ra is None or dec is None or not _in_field(grid, ra, dec):
            continue
        out.append({"id": row["source_id"], "ra": ra, "dec": dec, "epoch": GAIA_EPOCH,
                    "pmra_masyr": _f(row, "pmra"), "pmdec_masyr": _f(row, "pmdec"),
                    "g_mag": _f(row, "phot_g_mean_mag"), "parallax_mas": _f(row, "parallax"),
                    "parallax_error_mas": _f(row, "parallax_error")})
    return out


def parse_catwise(text: str, grid: Grid) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        ra, dec = _f(row, "ra_pm"), _f(row, "dec_pm")
        if ra is None or dec is None or not _in_field(grid, ra, dec):
            continue
        out.append({"id": row["source_name"], "ra": ra, "dec": dec, "epoch": CATWISE_EPOCH,
                    "pmra_masyr": _f(row, "pmra", 1000.0), "pmdec_masyr": _f(row, "pmdec", 1000.0),
                    "w1_mag": _f(row, "w1mpro"), "w2_mag": _f(row, "w2mpro")})
    return out


GAIA = "Gaia DR3"
CATWISE = "CatWISE2020"


def _failed(name: str) -> str:
    return f"{name} sources could not be fetched, so none are marked."


def gaia_failed(warnings: list[str]) -> bool:
    """True when `overlays` warned that the Gaia query failed (its list is then empty for
    want of an answer, not because the field has no Gaia sources)."""
    return _failed(GAIA) in warnings


def catwise_failed(warnings: list[str]) -> bool:
    """True when `overlays` warned that the CatWISE query failed."""
    return _failed(CATWISE) in warnings


def _one(name: str, job, parse, grid: Grid, deadline: float):
    """Parsed rows of a background query `job` if it answered by `deadline` (monotonic)."""
    try:
        return parse(job.result(timeout=max(0.0, deadline - time.monotonic())), grid), []
    except FutureTimeout:
        log.warning("%s query not answered within %g s; left out of this view", name,
                    OVERLAY_BUDGET_S)
    except Exception as exc:  # noqa: BLE001 - any failure must leave the view usable
        log.warning("%s query failed: %s", name, exc)
    return [], [_failed(name)]


def overlays(grid: Grid, fetch: Fetch = tap_csv, cache_dir: Path = CACHE_DIR,
             budget_s: float = OVERLAY_BUDGET_S):
    """(`overlays` dict, warnings). Each list is brightest first and capped at MAX_SOURCES.

    Gaia (ESA) and CatWISE (IRSA) are queried at once, each with Data Lab as fallback; this returns within about
    `budget_s` whatever the archives do."""
    deadline = time.monotonic() + budget_s
    def job(url: str, adql: str) -> Callable[[], str]:
        return lambda: cached_fetch(url, adql, fetch, cache_dir)

    g, c = gaia_query(grid), catwise_query(grid)
    # The primary is always asked. If it failed moments ago (its breaker is open), the mirror
    # is asked at the same moment rather than FALLBACK_AFTER_S later: no source is dropped.
    def after(url: str) -> float:
        return 0.0 if BREAKERS[url].is_open() else FALLBACK_AFTER_S

    g_job = background(first_answer, [job(GAIA_TAP, g), job(DATALAB_TAP, datalab_query(g, grid))],
                       after(GAIA_TAP))
    c_job = background(first_answer, [job(IRSA_TAP, c), job(DATALAB_TAP, datalab_query(c, grid))],
                       after(IRSA_TAP))
    gaia, w1 = _one(GAIA, g_job, parse_gaia, grid, deadline)
    cw, w2 = _one(CATWISE, c_job, parse_catwise, grid, deadline)
    return {"gaia": gaia, "catwise": cw}, w1 + w2
