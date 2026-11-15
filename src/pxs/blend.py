"""Warn when a Gaia star sits within one SPHEREx pixel of the target at the SPHEREx epochs.

Positions in degrees, proper motion in mas/yr (pmra includes cos dec), epochs as decimal
years. Gaia sources with no proper motion are kept fixed. The target itself, if it is in
Gaia, is recognised by position (within SELF_ARCSEC at the Gaia source's own epoch) and,
when both are known, by proper motion; it is never reported as a blend.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from pxs.astrometry import ARCSEC_PER_DEG, decimal_year, propagate
from pxs.grid import Grid
from pxs.target import Target

BLEND_ARCSEC = 6.2  # one SPHEREx pixel (6.15")
SELF_ARCSEC = 2.0
SELF_PM_FRACTION = 0.2  # proper motion must agree to 20% (or 50 mas/yr) to count as the target
SELF_PM_FLOOR_MASYR = 50.0


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation in arcsec (haversine)."""
    a1, d1, a2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((a2 - a1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * ARCSEC_PER_DEG


def _at(ra: float, dec: float, epoch: float, pmra, pmdec, year: float) -> tuple[float, float]:
    ra2, dec2 = propagate(ra, dec, epoch, pmra or 0.0, pmdec or 0.0, year)
    return float(ra2), float(dec2)


def _target_at(t: Target, year: float) -> tuple[float, float]:
    return _at(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, year)


def is_target(t: Target, src: dict) -> bool:
    """True when the Gaia source is the target: same place at its epoch and same motion."""
    ra, dec = _target_at(t, src["epoch"])
    if separation_arcsec(ra, dec, src["ra"], src["dec"]) > SELF_ARCSEC:
        return False
    if not t.has_pm or src.get("pmra_masyr") is None or src.get("pmdec_masyr") is None:
        return True
    dpm = math.hypot(t.pmra_masyr - src["pmra_masyr"], t.pmdec_masyr - src["pmdec_masyr"])
    return dpm <= max(SELF_PM_FLOOR_MASYR, SELF_PM_FRACTION * math.hypot(t.pmra_masyr,
                                                                          t.pmdec_masyr))


def closest_approach(t: Target, src: dict, years: Iterable[float]) -> float:
    """Smallest target-source separation (arcsec) over the given epochs."""
    seps = []
    for y in years:
        tra, tdec = _target_at(t, y)
        sra, sdec = _at(src["ra"], src["dec"], src["epoch"], src.get("pmra_masyr"),
                        src.get("pmdec_masyr"), y)
        seps.append(separation_arcsec(tra, tdec, sra, sdec))
    return min(seps)


def sky_neighbours(t: Target, gaia: Sequence[dict], year: float) -> list[tuple[float, float]]:
    """(ra, dec) degrees at `year` of the Gaia sources that are not the target."""
    return [_at(src["ra"], src["dec"], src["epoch"], src.get("pmra_masyr"),
                src.get("pmdec_masyr"), year) for src in gaia if not is_target(t, src)]


def field_px(t: Target, gaia: Sequence[dict], grid: Grid, year: float) -> list[tuple[float, float]]:
    """Grid pixel positions at `year` of the Gaia sources that are not the target."""
    sky = sky_neighbours(t, gaia, year)
    if not sky:
        return []
    x, y = grid.sky_to_px([ra for ra, _ in sky], [dec for _, dec in sky])  # one WCS for all
    return [(float(a), float(b)) for a, b in zip(x, y)]


MIN_PARALLAX_SNR = 5.0  # a Gaia parallax is fixed in the motion fit only when this significant


def target_parallax(t: Target, gaia: Sequence[dict]) -> float | None:
    """Parallax (mas) to fix in the motion fit: the target's own, else that of its Gaia row
    when positive and at least MIN_PARALLAX_SNR sigma; None otherwise (it is then fitted
    freely when there are enough epochs)."""
    if t.parallax_mas is not None:
        return t.parallax_mas
    for src in gaia:
        plx, err = src.get("parallax_mas"), src.get("parallax_error_mas")
        if plx is not None and err and plx > 0 and plx / err >= MIN_PARALLAX_SNR \
                and is_target(t, src):
            return float(plx)
    return None


def pass_years(passes: Sequence[Sequence]) -> list[float]:
    """Mean epoch (decimal year) of each pass of spectrum points."""
    return [float(decimal_year(np.mean([p.mjd for p in ps]))) for ps in passes if ps]


CLEARLY_BRIGHTER_MAG = 1.0  # target must be this much brighter than the neighbour in Gaia G


def blenders(t: Target, gaia: Sequence[dict], years: Sequence[float],
             radius_arcsec: float = BLEND_ARCSEC) -> list[tuple[dict, float]]:
    """(Gaia source, closest separation) for every non-target source within the radius."""
    if not years:
        return []
    out = []
    for src in gaia:
        if not is_target(t, src):
            sep = closest_approach(t, src, years)
            if sep < radius_arcsec:
                out.append((src, sep))
    return out


def blend_blocks_typing(t: Target, gaia: Sequence[dict], years: Sequence[float]) -> bool:
    """True when a neighbour within one SPHEREx pixel may dominate the target's spectrum: the
    target is not in Gaia (so it is fainter than the neighbour there) or is not at least
    CLEARLY_BRIGHTER_MAG brighter in G. Brown dwarfs are far redder than stars, so this errs
    on the side of not classifying."""
    near = blenders(t, gaia, years)
    if not near:
        return False
    me = [s for s in gaia if is_target(t, s) and s.get("g_mag") is not None]
    if not me:
        return True
    g_t = min(s["g_mag"] for s in me)
    return any(src.get("g_mag") is None or src["g_mag"] - g_t < CLEARLY_BRIGHTER_MAG
               for src, _ in near)


CATWISE_YEARS = (2010.0, 2019.0)  # CatWISE2020: WISE and NEOWISE data to the end of 2018
PIECE_ARCSEC = 3.0
PIECE_STEP_YEARS = 0.25


def is_catwise_piece(t: Target, src: dict) -> bool:
    """True when a CatWISE source is the target's own light: CatWISE breaks a fast mover into
    several sources along its path, often with wrong motions (Eps Ind B has six with W2
    10.7-13.4, 2MASS 0415-0935 four), so any source that comes within PIECE_ARCSEC of the
    target's track during CATWISE_YEARS counts as the target. A real star the target passed
    that closely in those years is therefore missed."""
    years = np.arange(CATWISE_YEARS[0], CATWISE_YEARS[1] + 1e-9, PIECE_STEP_YEARS)
    return min(separation_arcsec(*_target_at(t, y), *_at(src["ra"], src["dec"], src["epoch"],
                                                         src.get("pmra_masyr"),
                                                         src.get("pmdec_masyr"), y))
               for y in years) <= PIECE_ARCSEC


# Light of a bright neighbour inside SPHEREx's forced photometry (spherex.photometry fits the
# PSF to pixels within 3 px = 18" of the target). The PSF is taken as a Gaussian of the 2.4-5 um
# FWHM; the real PSF has broader wings, so the estimate is a lower limit.
#
# Two levels. A share of CONTAM_REFUSE or more refuses the type; CONTAM_CAUTION up to
# CONTAM_REFUSE keeps it but marks it provisional. 25% was chosen AFTER seeing which targets
# each level affects, so it is a judgement, not a calibrated value: at 10% UGPS J0722-0540 (a
# correct T9; W1 16.3 source 4.0" away, about 22%) and CWISE J2112-0529 (W2 16.7 at 4.9",
# about 15%) would be refused. WISE 1541-2250 (W1 16.6 at 2.0", estimated 2.4 times, and
# measured: SPHEREx 3.0-3.8 um flux 3.4 +- 0.5 times its own W1) is refused at any level.
CONTAM_FWHM_ARCSEC = 10.0
CONTAM_CAUTION = 0.10
CONTAM_REFUSE = 0.25
CHECKS_NOT_RUN = ("CatWISE2020 sources could not be fetched, so the checks for neighbours that "
                  "bias the measured positions or add light to the spectrum could not be run.")


def contaminant(t: Target, catwise: Sequence[dict], years: Sequence[float]) \
        -> tuple[str, float, float, float] | None:
    """(band, neighbour magnitude, closest separation arcsec, estimated light as a share of
    the target's) for the worst CatWISE neighbour over the SPHEREx `years`, when that share
    is at least CONTAM_CAUTION in W1 or W2; else None. Needs the target's W1 or W2 magnitude."""
    worst = None
    for src in catwise:
        if not years or is_catwise_piece(t, src):
            continue
        sep = closest_approach(t, src, years)
        psf = math.exp(-4.0 * math.log(2.0) * (sep / CONTAM_FWHM_ARCSEC) ** 2)
        for band, key in (("W1", "w1_mag"), ("W2", "w2_mag")):
            mine, theirs = getattr(t, key), src.get(key)
            if mine is None or theirs is None:
                continue
            share = 10 ** (-0.4 * (theirs - mine)) * psf
            if share >= CONTAM_CAUTION and (worst is None or share > worst[3]):
                worst = (band, float(theirs), sep, share)
    return worst


def contamination_reason(hit: tuple[str, float, float, float]) -> str:
    """A sentence for the manifest warnings when a `contaminant` hit refuses the type."""
    band, mag, sep, share = hit
    amount = f"{share:.0f} times" if share >= 1.0 else f"{share:.0%} of"
    return (f"The spectrum is not classified because a brighter catalogued source ({band} "
            f"{mag:.1f}) {sep:.1f} arcsec away falls inside the area the SPHEREx photometry "
            f"is fitted over; its light there is estimated at {amount} the target's own, "
            "or more.")


def contamination_caution(hit: tuple[str, float, float, float]) -> str:
    """A sentence for a `contaminant` hit below CONTAM_REFUSE: the type is kept, provisional."""
    band, mag, sep, share = hit
    return (f"A catalogued source ({band} {mag:.1f}) {sep:.1f} arcsec away may contribute "
            f"about {share:.0%} of the light at these wavelengths, or more; treat the type as "
            "provisional.")


def contamination_gate(t: Target, catwise: Sequence[dict] | None, years: Sequence[float]) \
        -> tuple[str | None, str | None]:
    """(refusal sentence, caution sentence), at most one of them set. `catwise` None means
    the catalogue could not be fetched, so nothing is checked (the caller says so with
    CHECKS_NOT_RUN)."""
    hit = None if catwise is None else contaminant(t, catwise, years)
    if hit is None:
        return None, None
    if hit[3] >= CONTAM_REFUSE:
        return contamination_reason(hit), None
    return None, contamination_caution(hit)


def blend_warnings(t: Target, gaia: Sequence[dict], years: Sequence[float],
                   radius_arcsec: float = BLEND_ARCSEC) -> list[str]:
    """One plain sentence per Gaia star (not the target) within `radius_arcsec` at any epoch."""
    out = []
    for src, sep in blenders(t, gaia, years, radius_arcsec):
        mag = "unknown G magnitude" if src.get("g_mag") is None else f"G = {src['g_mag']:.1f}"
        out.append(f"The SPHEREx spectrum may include light from a Gaia star ({mag}) that "
                   f"comes within {sep:.1f} arcsec of the target, less than one SPHEREx "
                   "pixel.")
    return out
