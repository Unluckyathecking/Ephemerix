"""Labels for candidates: known small body (JPL), catalogued star (Gaia, CatWISE), or an
unvetted candidate with its false-alarm probability from the null search.

A catalogue that cannot be reached leaves the label "unvetted" with a warning; nothing is
silently dropped.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from pxs.catalogs import (
    GAIA_TAP,
    IRSA_TAP,
    cached_fetch,
    catwise_query,
    gaia_query,
    parse_catwise,
    parse_gaia,
)
from pxs.grid import Grid

from .ephem import KnownObject, known_objects

log = logging.getLogger(__name__)

STAR_MATCH_PX = 1.5
GAIA_G_MAX = 16.0  # stars faint enough not to leave residuals are not used to veto
CATWISE_W1_MAX = 14.0
KNOWN_MATCH_ARCSEC = 20.0
NULL_REF_SNR = 5.0  # null peak count at this S/N anchors the false-alarm extrapolation
CATALOG_CAP = 5000


@dataclass(frozen=True)
class Stars:
    """Bright catalogued stars on the grid, as pixel-index coordinates."""

    x: np.ndarray
    y: np.ndarray
    warnings: tuple[str, ...]


def bright_stars(grid: Grid) -> Stars:
    """Gaia G < GAIA_G_MAX and CatWISE W1 < CATWISE_W1_MAX sources in the field."""
    xs, ys, warns = [], [], []
    try:
        gaia = parse_gaia(cached_fetch(GAIA_TAP, gaia_query(grid, cap=CATALOG_CAP)), grid)
        pts = [(g["ra"], g["dec"]) for g in gaia if (g.get("g_mag") or 99) < GAIA_G_MAX]
    except Exception as e:  # noqa: BLE001 - a missing catalogue must not stop the search
        log.warning("Gaia query failed: %s", e)
        pts, warns = [], ["Gaia stars could not be fetched; star coincidences not checked."]
    try:
        cw = parse_catwise(cached_fetch(IRSA_TAP, catwise_query(grid, cap=CATALOG_CAP)), grid)
        pts += [(c["ra"], c["dec"]) for c in cw if (c.get("w1_mag") or 99) < CATWISE_W1_MAX]
    except Exception as e:  # noqa: BLE001
        log.warning("CatWISE query failed: %s", e)
        warns.append("CatWISE sources could not be fetched; star coincidences not checked.")
    if pts:
        x, y = grid.sky_to_px(np.array([p[0] for p in pts]), np.array([p[1] for p in pts]))
        xs, ys = list(np.asarray(x) - 0.5), list(np.asarray(y) - 0.5)
    return Stars(np.array(xs), np.array(ys), tuple(warns))


def near_star(stars: Stars, x: float, y: float) -> bool:
    return bool(stars.x.size and np.min(np.hypot(stars.x - x, stars.y - y)) <= STAR_MATCH_PX)


def field_known_objects(grid: Grid, mjd: float) -> tuple[list[KnownObject], tuple[str, ...]]:
    """JPL-catalogued small bodies in the field at mid-pass."""
    half = grid.fov_arcsec / 3600 / 2 + 0.02
    try:
        return known_objects(grid.center_ra, grid.center_dec, half, mjd), ()
    except Exception as e:  # noqa: BLE001
        log.warning("JPL small-body identification failed: %s", e)
        return [], ("JPL small-body identification failed; known objects not matched.",)


def match_known(objs: list[KnownObject], ra: float, dec: float) -> KnownObject | None:
    """The catalogued body within KNOWN_MATCH_ARCSEC of (ra, dec), if any."""
    best, best_sep = None, KNOWN_MATCH_ARCSEC
    for o in objs:
        sep = math.hypot((o.ra - ra) * math.cos(math.radians(dec)), o.dec - dec) * 3600
        if sep <= best_sep:
            best, best_sep = o, sep
    return best


def expected_false(snr: float, null_snrs: list[float]) -> float:
    """Expected number of null peaks per field-pass at or above `snr`.

    Counted directly from the mirrored null search where it has peaks that bright;
    beyond them, extrapolated from its count at NULL_REF_SNR with a Gaussian tail
    (N(>= s) = N(>= 5) x Q(s) / Q(5)), which is optimistic if the real tail is heavier.
    """
    n_ref = sum(s >= NULL_REF_SNR for s in null_snrs)
    direct = sum(s >= snr for s in null_snrs)
    extrap = max(n_ref, 1) * norm.sf(snr) / norm.sf(NULL_REF_SNR)
    return float(max(direct, extrap)) if direct else float(extrap)


def false_alarm_probability(snr: float, null_snrs: list[float]) -> float:
    """P(at least one null peak this bright in the field-pass) = 1 - exp(-N)."""
    return float(1.0 - math.exp(-expected_false(snr, null_snrs)))
