"""Turn measured completeness fluxes into "how big and how far" statements.

Reflected light: a body of radius R and geometric albedo p at distance d (au, r ~ Delta ~ d,
phase angle neglected, which is generous by <= 0.1 mag at 30 au) has
V = H + 10 log10(d), H = 5 log10(1329 km / (D sqrt(p))). The search reports flux at 1 um
for a solar-coloured body; V follows from the solar colour of the same template.
A body must also move at least the search's minimum motion within the pass; a body at rest
at distance d moves max|reflex dt + curve| / d px, which caps the distance from above.

Thermal: the flux scales as d^-2 at fixed temperature; the reference fluxes are Fortney et
al. (2016) W1 values at 622 au.
"""

from __future__ import annotations

import math

import numpy as np

from .geometry import PassGeometry
from .matched import reflected_template

R_EARTH_KM = 6371.0
AB_ZERO_JY = 3631.0
# F_nu(0.55 um) / F_nu(1.0 um) for the reflected-sunlight template.
V_OVER_1UM = float(reflected_template(np.array([0.55]))[0])

PLANETS = (  # (label, radius in Earth radii, geometric albedo)
    ("Neptune-sized (3.9 R_E, p 0.4)", 3.9, 0.4),
    ("Planet Nine, 3.5 R_E, p 0.4 (Brown & Batygin)", 3.5, 0.4),
    ("super-Earth, 2 R_E, p 0.4", 2.0, 0.4),
    ("Neptune-sized, dark (3.9 R_E, p 0.1)", 3.9, 0.1),
)

FORTNEY_622AU_UJY = {  # W1 Vega -> uJy at 622 au (next-phase.md A2)
    "50 K, CH4 1e-6 solar (most optimistic)": 112.0,
    "50 K, CH4 1e-3 solar": 7.8,
    "40 K, CH4 1e-6 solar": 2.0,
}


def ab_mag(flux_ujy: float) -> float:
    return -2.5 * math.log10(flux_ujy * 1e-6 / AB_ZERO_JY) if flux_ujy > 0 else math.nan


def vmag_from_1um(flux_ujy: float) -> float:
    """V (taken as AB at 0.55 um) of a solar-coloured body with this flux at 1 um."""
    return ab_mag(flux_ujy * V_OVER_1UM) if flux_ujy > 0 else math.nan


def absolute_mag(radius_rearth: float, albedo: float) -> float:
    d_km = 2 * radius_rearth * R_EARTH_KM
    return 5 * math.log10(1329.0 / (d_km * math.sqrt(albedo)))


def reflected_distance(vlim: float, radius_rearth: float, albedo: float) -> float:
    """Distance (au) at which the body fades to vlim."""
    return 10 ** ((vlim - absolute_mag(radius_rearth, albedo)) / 10)


def motion_distance(geom: PassGeometry, min_motion_px: float) -> float:
    """Largest distance (au) at which a body at rest still moves min_motion_px from its
    mid-pass position within this pass (reflex plus parallax curvature)."""
    off = np.outer(geom.reflex_px_day, geom.dt) + geom.curve_px
    span = float(np.max(np.hypot(*off))) if off.size else 0.0
    return span / min_motion_px if min_motion_px > 0 else math.inf


def thermal_distance(flux_ujy: float, ref_ujy_622: float) -> float:
    """Distance (au) at which a model with ref_ujy_622 at 622 au fades to flux_ujy."""
    return 622.0 * math.sqrt(ref_ujy_622 / flux_ujy) if flux_ujy > 0 else math.nan


def distance_curves(vlim: float, d_motion: float) -> list[dict]:
    """Per planet model: brightness limit, motion limit, and the binding one (au)."""
    out = []
    for label, r, p in PLANETS:
        db = reflected_distance(vlim, r, p) if math.isfinite(vlim) else math.nan
        out.append({"model": label, "radius_rearth": r, "albedo": p, "d_bright_au": db,
                    "d_motion_au": d_motion,
                    "d_max_au": min(db, d_motion) if math.isfinite(db) else math.nan})
    return out


def statement(vlim50: float, d_motion: float) -> str:
    """One honest sentence for the field."""
    if not math.isfinite(vlim50):
        return "Completeness never reached 50% in this field-pass; no limit is claimed."
    c = distance_curves(vlim50, d_motion)[0]
    binding = "brightness" if c["d_bright_au"] <= d_motion else "motion within the pass"
    return (f"In this field and pass, the search is 50% complete to V {vlim50:.1f} for a "
            f"solar-coloured mover. A Neptune-sized planet (3.9 Earth radii, albedo 0.4) "
            f"would have been seen out to about {c['d_max_au']:.0f} au, limited by "
            f"{binding}. Planet Nine is predicted fainter than V 21.5, so it is out of reach.")
