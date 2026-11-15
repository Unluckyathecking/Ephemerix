"""Solar F_nu reference and reflectance spectra.

The reference is the CALSPEC solar model sun_mod_001 (Kurucz special model, T/g 5777/4.4,
normalised to the observed Sun at 0.68-0.77 um by R. Bohlin; CALSPEC: Bohlin, Gordon &
Tremblay 2014, PASP 126, 711, doi:10.1086/677655), public STScI data, binned to R = 1000 in
solar_ref.csv by probes/solarsystem/make_solar_table.py. In R = 40 bins over 0.75-2.68 um it
agrees with the observed CALSPEC Sun (sun_reference_stis_002) to 0.4% rms. A 5777 K
blackbody is not adequate: relative to the model it is 12% low at 1.67 um (H- opacity
minimum) and 24% high at 4.6 um (CO band), which would print false "bands" in a
reflectance spectrum.

Reflectance here is relative: R(lambda) = F_nu(body) / F_nu(Sun), averaged over each
point's bandwidth, divided by its mean over a continuum window. Thermal emission is not
removed (see `thermal_fraction`); for the trans-Neptunian bodies it is negligible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

TABLE = Path(__file__).with_name("solar_ref.csv")
NORM_WINDOW_UM = (0.75, 1.30)  # continuum: short of the strong H2O and CH4 ice bands
H, C, K = 6.62607015e-34, 2.99792458e8, 1.380649e-23
SUN_TEFF_K = 5772.0
R_SUN_AU = 0.00465047


@lru_cache(maxsize=1)
def _table() -> tuple[np.ndarray, np.ndarray]:
    a = np.loadtxt(TABLE, delimiter=",", comments="#", skiprows=3)
    return a[:, 0], a[:, 1]


def solar_fnu(wl_um: float, bw_um: float = 0.0) -> float:
    """Relative solar F_nu averaged over [wl - bw/2, wl + bw/2] (um); 1.0 at 1.25 um."""
    w, f = _table()
    if not (w[0] <= wl_um <= w[-1]):
        raise ValueError(f"wavelength {wl_um} um outside the solar table {w[0]:.2f}-{w[-1]:.2f}")
    if bw_um <= 0:
        return float(np.interp(wl_um, w, f))
    lo, hi = wl_um - bw_um / 2, wl_um + bw_um / 2
    grid = np.linspace(max(lo, w[0]), min(hi, w[-1]), 41)
    return float(np.mean(np.interp(grid, w, f)))


@dataclass(frozen=True)
class RPoint:
    """One reflectance point: relative reflectance and its 1-sigma error (dimensionless)."""

    wl_um: float
    bw_um: float
    refl: float
    err: float


def reflectance(points: list[dict], norm_window: tuple[float, float] = NORM_WINDOW_UM
                ) -> tuple[list[RPoint], float | None]:
    """Reflectance from manifest-style spectrum points ({wl_um, bw_um, flux, err, flagged}).

    Returns the points normalised to the inverse-variance mean over `norm_window`, and
    that mean in mJy-per-solar-unit (None, and no points, if the window has no data).
    Flagged points are dropped. The normalisation error is not folded into each point:
    it scales the whole spectrum, so band ratios are unaffected.
    """
    raw = []
    for p in points:
        if p.get("flagged") or p.get("flux") is None or not p.get("err"):
            continue
        s = solar_fnu(p["wl_um"], p.get("bw_um") or 0.0)
        raw.append((p["wl_um"], p.get("bw_um") or 0.0, p["flux"] / s, p["err"] / s))
    lo, hi = norm_window
    win = [(r, e) for w, _, r, e in raw if lo <= w < hi and e > 0]
    if not win:
        return [], None
    wts = np.array([1 / e**2 for _, e in win])
    norm = float(np.sum(wts * np.array([r for r, _ in win])) / np.sum(wts))
    if not (math.isfinite(norm) and norm > 0):
        return [], None
    return [RPoint(w, b, r / norm, e / norm) for w, b, r, e in raw], norm


def planck_nu(wl_um: float, t_k: float) -> float:
    """B_nu in W m^-2 Hz^-1 sr^-1."""
    nu = C / (wl_um * 1e-6)
    x = H * nu / (K * t_k)
    return 0.0 if x > 700 else 2 * H * nu**3 / C**2 / math.expm1(x)


def thermal_fraction(wl_um: float, r_au: float, geometric_albedo: float,
                     bond_albedo: float = 0.5, eta: float = 1.0) -> float:
    """Thermal over reflected F_nu at wl_um for a body at r_au, at zero phase.

    Uses the subsolar temperature T_ss = [(1 - A) S / (eta eps sigma)]^1/4 (eps = 0.9) as an
    upper bound on the surface temperature, emitting from the whole disc: an upper bound
    on the thermal share. Reflected: p * F_sun(r). Thermal: eps * B_nu(T_ss) * pi.
    Both per unit cross-section, so size cancels.
    """
    sigma, s0, eps = 5.670374419e-8, 1361.0, 0.9
    t_ss = ((1 - bond_albedo) * s0 / r_au**2 / (eta * eps * sigma)) ** 0.25
    f_sun = planck_nu(wl_um, SUN_TEFF_K) * math.pi * (R_SUN_AU / r_au) ** 2
    reflected = geometric_albedo * f_sun
    thermal = eps * planck_nu(wl_um, t_ss) * math.pi
    return thermal / reflected if reflected > 0 else math.inf


def thermal_cutoff_um(r_au: float, geometric_albedo: float = 0.05, bond_albedo: float = 0.02,
                      share: float = 0.1) -> float | None:
    """Shortest wavelength (um, <= 5) where thermal emission may exceed `share` of the
    reflected flux, for a dark (worst-case) surface at r_au; None if nowhere below 5 um.

    Beyond it a "reflectance" is not one. For the trans-Neptunian bodies this is None
    (thermal/reflected < 1e-13 at 5 um); for (153) Hilda at 4.1 au it is about 3.9 um.
    """
    for w in np.arange(2.0, 5.0001, 0.01):
        if thermal_fraction(float(w), r_au, geometric_albedo, bond_albedo) > share:
            return round(float(w), 2)
    return None
