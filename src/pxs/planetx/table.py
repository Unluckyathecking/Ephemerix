"""Build the Planet X limits table (flux vs distance, depths, detection distances, motion)."""

from __future__ import annotations

from collections.abc import Callable

from . import cases as C
from . import motion
from .depths import Depth
from .flux import band_flux_ujy, v_mag
from .photometry import ALL_BANDS, ab_mag, ujy_from_ab

DISTANCES_AU = tuple(range(200, 1501, 25))
MOTION_DISTANCES_AU = (200, 300, 400, 500, 700, 1000, 1500)
PASS_DAYS = 14  # a typical SPHEREx pass at mid-latitudes


def ab_curve(case: C.Case, band_name: str,
             pick: Callable[[C.Case], tuple[float, float, float]]) -> list[float]:
    band = next(b for b in ALL_BANDS if b.name == band_name)
    r_re, p, t = pick(case)
    return [round(ab_mag(band_flux_ujy(band, d, r_re, p, t)), 3) for d in DISTANCES_AU]


def fortney_curve(band_name: str, which: int) -> list[float]:
    """Methane-depleted thermal W1/W2 (Fortney Table 2), Neptune radius, falls as distance^-2."""
    band = next(b for b in ALL_BANDS if b.name == band_name)
    ujy0 = ujy_from_ab(C.FORTNEY_VEGA[band_name][which] + band.vega_to_ab)
    return [round(ab_mag(ujy0 * (C.FORTNEY_DIST_AU / d) ** 2), 3) for d in DISTANCES_AU]


def reach_au(curve: list[float], depth_ab: float) -> str | int:
    """Largest grid distance where the planet is at least as bright as depth_ab.

    "<200" if fainter everywhere, ">1500" if brighter everywhere (curves fall with distance).
    """
    inside = [d for d, m in zip(DISTANCES_AU, curve) if m <= depth_ab]
    if not inside:
        return f"<{DISTANCES_AU[0]}"
    if inside[-1] == DISTANCES_AU[-1]:
        return f">{DISTANCES_AU[-1]}"
    return inside[-1]


def detection(curves: dict[str, list[float]], depth: Depth) -> dict[str, dict]:
    """Per band: reach for (faint planet, shallow depth), (nominal, mid), (bright, deep)."""
    out = {}
    for band, (shallow, deep) in depth.ab.items():
        cv = curves[band]
        out[band] = {"lo": reach_au(cv["lo"], shallow), "nom": reach_au(cv["nom"], (shallow + deep) / 2),
                     "hi": reach_au(cv["hi"], deep)}
    return out


def case_block(case: C.Case, depths: list[Depth]) -> dict:
    curves = {b.name: {"lo": ab_curve(case, b.name, C.low), "nom": ab_curve(case, b.name, C.nominal),
                       "hi": ab_curve(case, b.name, C.high)} for b in ALL_BANDS}
    return {
        "key": case.key, "label": case.label, "note": case.note,
        "radius_re": case.radius_re, "albedo": case.albedo, "teff_k": case.teff_k,
        "ab": curves,
        "v_nom": [round(v_mag(d, case.radius_re[1], case.albedo[1]), 2) for d in DISTANCES_AU],
        "reach_au": {d.key: detection(curves, d) for d in depths},
    }


def motion_rows() -> list[dict]:
    rows = []
    for r in MOTION_DISTANCES_AU:
        par, orb = motion.shift_between_passes_arcmin(r)
        rows.append({
            "r_au": r,
            "between_passes_arcmin": round(par + orb, 1),
            "parallax_part_arcmin": round(par, 1),
            "per_day_arcsec": {str(b): round(motion.rate_arcsec_per_day(r, b), 2) for b in (0, 30, 60)},
            "in_pass_px": {str(b): round(motion.to_pixels(motion.smear_in_pass_arcsec(r, b, PASS_DAYS)), 1)
                           for b in (0, 30, 60)},
        })
    return rows


def build(depths: list[Depth]) -> dict:
    return {
        "schema": 1,
        "distances_au": list(DISTANCES_AU),
        "bands": [{"name": b.name, "lo_um": b.lo_um, "hi_um": b.hi_um} for b in ALL_BANDS],
        "depths": [{"key": d.key, "label": d.label, "kind": d.kind, "per": d.per, "note": d.note,
                    "ab": {k: list(v) for k, v in d.ab.items()}} for d in depths],
        "cases": [case_block(c, depths) for c in C.CASES],
        "fortney_methane_depleted": {
            "label": "Methane-depleted atmosphere, Neptune radius (Fortney et al. 2016, Table 2)",
            "ab": {b: {"lo": fortney_curve(b, 0), "hi": fortney_curve(b, 1)} for b in C.FORTNEY_VEGA},
        },
        "motion": {"pass_days": PASS_DAYS, "pixel_arcsec": motion.SPHEREX_PIXEL_ARCSEC,
                   "rows": motion_rows()},
    }
