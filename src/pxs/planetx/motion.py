"""Apparent sky motion of a distant planet seen at about 90 deg from the Sun.

SPHEREx (like WISE) observes near 90 deg solar elongation. There Earth's offset from the Sun
(1 au) is across the line of sight, so passes six months apart see the planet displaced by
twice the parallax, 2 / r rad, whatever its ecliptic latitude. Earth's velocity (29.78 km/s)
lies along the line of sight in the ecliptic and fully across it at the ecliptic pole, so
the rate within one pass is v_E |sin(beta)| + v_orb over the distance, where beta is the
ecliptic latitude. The planet's own motion assumes a circular orbit with all of it across the
line of sight, an upper bound (an eccentric planet near aphelion moves slower).
"""

from __future__ import annotations

import math

ARCSEC_PER_RAD = 206264.806
AU_KM = 1.495978707e8
V_EARTH_KMS = 29.78
YEAR_DAYS = 365.25
SPHEREX_PIXEL_ARCSEC = 6.15


def orbital_speed_kms(r_au: float) -> float:
    """Circular orbital speed at r_au from the Sun."""
    return V_EARTH_KMS / math.sqrt(r_au)


def shift_between_passes_arcmin(r_au: float, dt_years: float = 0.5) -> tuple[float, float]:
    """(parallax part, orbital part) of the shift between passes dt_years apart, arcmin."""
    parallax = 2 / r_au * ARCSEC_PER_RAD / 60
    orbital = 360 * 60 / r_au**1.5 * dt_years  # heliocentric angular motion, circular orbit
    return parallax, orbital


def rate_arcsec_per_day(r_au: float, beta_deg: float) -> float:
    """Upper-bound sky rate within one pass at ecliptic latitude beta_deg, arcsec per day."""
    v = V_EARTH_KMS * abs(math.sin(math.radians(beta_deg))) + orbital_speed_kms(r_au)
    return v * 86400 / (r_au * AU_KM) * ARCSEC_PER_RAD


def smear_in_pass_arcsec(r_au: float, beta_deg: float, days: float) -> float:
    """Motion across one pass of `days`, centred on quadrature, arcsec (upper bound).

    Adds the curvature of the parallax ellipse, which matters only near the ecliptic.
    """
    half = math.pi * days / YEAR_DAYS
    curvature = (1 - math.cos(half)) / r_au * ARCSEC_PER_RAD
    return rate_arcsec_per_day(r_au, beta_deg) * days + curvature


def to_pixels(arcsec: float) -> float:
    return arcsec / SPHEREX_PIXEL_ARCSEC
