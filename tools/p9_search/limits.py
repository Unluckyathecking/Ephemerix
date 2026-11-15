"""Pure arithmetic for the pilot's limits: binned completeness, Wilson intervals, magnitude
conversions, reach against the planetx cases, and the reference-population exclusion."""

from __future__ import annotations

import math

import numpy as np

from pxs.movers.completeness import Curve
from pxs.movers.limits import AB_ZERO_JY, V_OVER_1UM

FLUX_EDGES_UJY = np.geomspace(20.0, 400.0, 9)  # 8 log bins over the injected range
Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials ((nan, nan) for n = 0)."""
    if n == 0:
        return math.nan, math.nan
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def binned(flux_ujy: np.ndarray, recovered: np.ndarray,
           edges: np.ndarray = FLUX_EDGES_UJY) -> dict:
    """Completeness per log-flux bin: centres (uJy), k, n, fraction, Wilson bounds."""
    f, r = np.asarray(flux_ujy, float), np.asarray(recovered, bool)
    idx = np.clip(np.digitize(f, edges) - 1, 0, len(edges) - 2)
    n = np.bincount(idx, minlength=len(edges) - 1)
    k = np.bincount(idx, weights=r, minlength=len(edges) - 1).astype(int)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(n > 0, k / np.maximum(n, 1), np.nan)
    ci = [wilson(int(a), int(b)) for a, b in zip(k, n)]
    return {"flux_ujy": np.sqrt(edges[:-1] * edges[1:]).tolist(), "k": k.tolist(),
            "n": n.tolist(), "completeness": frac.tolist(),
            "lo95": [c[0] for c in ci], "hi95": [c[1] for c in ci]}


def flux_at(b: dict, level: float) -> float:
    """Faintest flux (uJy) above which binned completeness stays >= level (Curve.flux_at)."""
    c = Curve(np.array(b["flux_ujy"]) / 1e3, np.array(b["completeness"], float),
              np.array(b["n"]))
    return c.flux_at(level) * 1e3


def flux_1um_from_vmag(v: np.ndarray | float) -> np.ndarray | float:
    """Inverse of pxs.movers.limits.vmag_from_1um: uJy at 1 um of a solar-coloured body."""
    return AB_ZERO_JY * 1e6 * 10 ** (-0.4 * np.asarray(v, float)) / V_OVER_1UM


def ab_from_ujy(flux_ujy: float) -> float:
    return -2.5 * math.log10(flux_ujy * 1e-6 / AB_ZERO_JY)


def completeness_at(b: dict, flux_ujy: np.ndarray) -> np.ndarray:
    """Completeness interpolated in log flux from bin centres; clamped to the end bins."""
    x = np.log(np.array(b["flux_ujy"]))
    y = np.array(b["completeness"], float)
    ok = np.isfinite(y)
    if not ok.any():
        return np.zeros(np.shape(flux_ujy))
    return np.interp(np.log(np.asarray(flux_ujy, float)), x[ok], y[ok])


def reach_au(distances: list[float], mags: list[float], mag_limit: float) -> float | None:
    """Largest tabulated distance at which the model is at least as bright as mag_limit
    (None if it is fainter at every distance; mags must grow with distance)."""
    ok = [d for d, m in zip(distances, mags) if m <= mag_limit]
    return float(max(ok)) if ok else None


def excluded_fraction(density: float, area_deg2: float, comp: np.ndarray,
                      r_au: np.ndarray, d_motion_au: float, d_max_au: float = 1000.0) -> float:
    """Expected fraction of the whole population excluded by one tile: the population mass
    in the tile (density x area) times the mean, over local members, of completeness at
    their brightness, counting only members close enough to move >= the minimum and inside
    the search's distance range."""
    if len(comp) == 0:
        return 0.0
    inside = (np.asarray(r_au) <= min(d_motion_au, d_max_au)).astype(float)
    return float(density * area_deg2 * np.mean(np.asarray(comp) * inside))
