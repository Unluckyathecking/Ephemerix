"""Flux density of a distant planet: reflected sunlight plus blackbody emission.

Reflected: F = F_sun(1 au) * p * (R / Delta)^2 / r^2 (r in au), at zero phase angle (at 200 au
and beyond the phase angle is under 0.3 deg). SPHEREx and WISE look at about 90 deg solar
elongation, so Delta = sqrt(r^2 - 1); we use Delta = r (error under 1e-5 at 200 au).
The albedo is taken as grey (one number at all wavelengths). That is optimistic for a
methane-bearing atmosphere, which is dark in the 1.7, 2.3 and 3.3 um bands; treat the
reflected flux as an upper bound there.

Solar spectrum: the repo's CALSPEC solar model table (pxs.solarsystem.solar, relative F_nu,
1.0 at 1.25 um) scaled to the Sun's apparent 2MASS J magnitude of -27.03 AB (Willmer 2018,
ApJS 236, 47, Table 3: M_J = 4.54 AB at 10 pc). Checked against (V - W1)_sun = 1.608
(Casagrande et al. 2012) in the tests.

Thermal: pi * B_nu(T_eff) * (R / Delta)^2. A blackbody is the lower bracket at 3-5 um; real
cold H2 atmospheres can be far brighter there (Fortney et al. 2016), handled in cases.py.
"""

from __future__ import annotations

import math

from pxs.solarsystem.solar import solar_fnu

from .photometry import Band, band_mean, ujy_from_ab

H, C, K = 6.62607015e-34, 2.99792458e8, 1.380649e-23
AU_M = 1.495978707e11
R_EARTH_M = 6.371e6
JY = 1e-26  # W m^-2 Hz^-1
SUN_J_AB_1AU = 4.54 - 5 * math.log10(10 * 206264.806)  # -27.03: M_J(AB) moved to 1 au
SUN_UJY_AT_1P25 = ujy_from_ab(SUN_J_AB_1AU)


def sun_ujy_1au(wl_um: float) -> float:
    """Solar flux density at 1 au, microjansky."""
    return SUN_UJY_AT_1P25 * solar_fnu(wl_um)


def reflected_ujy(wl_um: float, r_au: float, radius_re: float, albedo: float) -> float:
    """Reflected sunlight from a planet at r_au from the Sun and from us, microjansky."""
    ratio = radius_re * R_EARTH_M / (r_au * AU_M)
    return sun_ujy_1au(wl_um) * albedo * ratio**2 / r_au**2


def planck_nu(wl_um: float, t_k: float) -> float:
    """Planck B_nu in W m^-2 Hz^-1 sr^-1."""
    nu = C / (wl_um * 1e-6)
    x = H * nu / (K * t_k)
    if x > 700:
        return 0.0
    return 2 * H * nu**3 / C**2 / math.expm1(x)


def thermal_ujy(wl_um: float, t_k: float, radius_re: float, delta_au: float) -> float:
    """Blackbody emission of a sphere of radius radius_re at delta_au, microjansky."""
    ratio = radius_re * R_EARTH_M / (delta_au * AU_M)
    return math.pi * planck_nu(wl_um, t_k) * ratio**2 / JY * 1e6


SUN_V_VEGA_1AU = -26.76  # Willmer 2018, Table 3


def v_mag(r_au: float, radius_re: float, albedo: float) -> float:
    """Reflected-light V magnitude (Vega), for comparison with optical surveys."""
    ratio = radius_re * R_EARTH_M / (r_au * AU_M)
    return SUN_V_VEGA_1AU - 2.5 * math.log10(albedo * ratio**2 / r_au**2)


def band_flux_ujy(band: Band, r_au: float, radius_re: float, albedo: float,
                  teff_k: float) -> float:
    """Band-mean reflected plus blackbody flux density, microjansky."""
    return band_mean(lambda w: reflected_ujy(w, r_au, radius_re, albedo)
                     + thermal_ujy(w, teff_k, radius_re, r_au), band)
