"""The manifest's optional `vetting` block: WISE colour and reduced proper motion.

    { "w1_mag", "w2_mag", "w1_w2", "reduced_pm_w2", "catalogue" }   (all nullable)

Magnitudes are Vega. The target list's magnitudes win when given (CatWISE fits fast movers
badly and can split them); otherwise the CatWISE2020 row matching the target. Reduced proper
motion H_W2 = W2 + 5 log10(mu) + 5 with mu in arcsec/yr, from the target's proper motion
when known, else CatWISE's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pxs.astrometry import propagate
from pxs.blend import separation_arcsec
from pxs.catalogs import CATWISE_EPOCH
from pxs.target import Target

MATCH_ARCSEC = 3.0  # CatWISE row within this of the target at the CatWISE epoch


def _target_at(t: Target, year: float) -> tuple[float, float]:
    if not t.has_pm:
        return t.ra, t.dec
    ra, dec = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, year)
    return float(ra), float(dec)


def catwise_row(t: Target, catwise: Sequence[dict]) -> dict | None:
    """The CatWISE source nearest the target at the CatWISE epoch, within MATCH_ARCSEC."""
    ra, dec = _target_at(t, CATWISE_EPOCH)
    best = min(catwise, key=lambda s: separation_arcsec(ra, dec, s["ra"], s["dec"]), default=None)
    if best is None or separation_arcsec(ra, dec, best["ra"], best["dec"]) > MATCH_ARCSEC:
        return None
    return best


def _pm_arcsec(t: Target, row: dict | None) -> float | None:
    if t.has_pm:
        return math.hypot(t.pmra_masyr, t.pmdec_masyr) / 1000.0
    if row and row.get("pmra_masyr") is not None and row.get("pmdec_masyr") is not None:
        return math.hypot(row["pmra_masyr"], row["pmdec_masyr"]) / 1000.0
    return None


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


def vetting(t: Target, catwise: Sequence[dict]) -> dict:
    """The vetting block for a target, from its own magnitudes and the CatWISE overlay rows."""
    row = catwise_row(t, catwise)
    w1 = t.w1_mag if t.w1_mag is not None else (row or {}).get("w1_mag")
    w2 = t.w2_mag if t.w2_mag is not None else (row or {}).get("w2_mag")
    mu = _pm_arcsec(t, row)
    h = w2 + 5.0 * math.log10(mu) + 5.0 if w2 is not None and mu else None
    return {"w1_mag": _r(w1), "w2_mag": _r(w2),
            "w1_w2": _r(w1 - w2) if w1 is not None and w2 is not None else None,
            "reduced_pm_w2": _r(h),
            "catalogue": f"CatWISE2020 {row['id']}" if row else None}
