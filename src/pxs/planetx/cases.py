"""Hypothetical planets, each with (low, nominal, high) radius, albedo and effective temperature.

Sources for every number:
- Super-Earth 5 M_E and 10 M_E: nominal radius and T_eff from Linder & Mordasini 2016 (A&A 589,
  A134; 5 M_E: 2.92 R_E, 40 K; 10 M_E: 3.66 R_E, 47 K). Ranges span Fortney et al. 2016
  (ApJL 824, L25) Table 1 at 4.5 Gyr (5 M_E: 2.71-4.12 R_E, 36.7-42.2 K; 10 M_E: 3.16-5.09 R_E,
  40.1-48.3 K). The favoured mass is 6.2 (+2.2/-1.3) M_E at a = 380 (+140/-80) au
  (Brown & Batygin 2021, AJ 162, 219), so these two bracket it.
- Neptune analogue: radius 3.865 R_E (24,622 km). T_eff 43-54 K: isolated 15-20 M_E models
  (Fortney Table 1, 42.8-50.6 K; Linder & Mordasini 20 M_E, 54 K). Real Neptune's 59 K is
  partly sunlight at 30 au.
- Jupiter analogue: radius 10.97 R_E (69,911 km). T_eff about 100 K, from Jupiter's internal
  heat flux of 7.5 W/m^2 (Li et al. 2018, Nat. Commun. 9, 3709). A blackbody badly
  underestimates a giant's 4-5 um window flux, so this case is a lower bound at W2 and D5-D6.
- Geometric albedo, grey: 0.41 nominal (Neptune-like, as in Linder & Mordasini), 0.75 high (deep
  Rayleigh-scattering H2 atmosphere, Fortney et al. 2016), 0.1 low (our stand-in for the
  methane darkening of 1-5 um light; an assumption, not a published value). Jupiter: 0.54
  nominal (Mallama et al. 2017, Icarus 282, 19, V band).

Methane-depleted thermal emission (Fortney et al. 2016, Table 2): cloud-free models with CH4
at 1e-6 put W1 = 20.5 (T_eff 40 K) to 16.1 (50 K) and W2 = 22.8 to 17.2 (Vega) at 622 au for
Neptune's radius. That light comes from the interior, so it falls only as distance^-2.
"""

from __future__ import annotations

from dataclasses import dataclass

Triple = tuple[float, float, float]  # (low, nominal, high)
ALBEDO: Triple = (0.1, 0.41, 0.75)
R_NEPTUNE_RE = 3.865


@dataclass(frozen=True)
class Case:
    key: str
    label: str
    radius_re: Triple
    albedo: Triple
    teff_k: Triple
    note: str


CASES: tuple[Case, ...] = (
    Case("se5", "Super-Earth, 5 Earth masses", (2.71, 2.92, 4.12), ALBEDO, (36.7, 40.0, 42.2),
         "Linder & Mordasini 2016; Fortney et al. 2016 Table 1"),
    Case("se10", "Super-Earth, 10 Earth masses", (3.16, 3.66, 5.09), ALBEDO, (40.1, 47.0, 48.3),
         "Linder & Mordasini 2016 nominal Planet Nine; Fortney et al. 2016 Table 1"),
    Case("neptune", "Neptune analogue", (R_NEPTUNE_RE,) * 3, ALBEDO, (43.0, 50.0, 54.0),
         "Fortney et al. 2016 Table 1; Linder & Mordasini 2016"),
    Case("jupiter", "Jupiter analogue", (10.97,) * 3, (0.1, 0.54, 0.75), (95.0, 100.0, 105.0),
         "Li et al. 2018; Mallama et al. 2017. Blackbody: a lower bound at 4-5 um"),
)

# Fortney et al. 2016 Table 2, CH4 = 1e-6: (T_eff 40 K, T_eff 50 K) Vega magnitudes at 622 au.
FORTNEY_DIST_AU = 622.0
FORTNEY_VEGA = {"WISE W1": (20.5, 16.1), "WISE W2": (22.8, 17.2)}


def low(case: Case) -> tuple[float, float, float]:
    return case.radius_re[0], case.albedo[0], case.teff_k[0]


def nominal(case: Case) -> tuple[float, float, float]:
    return case.radius_re[1], case.albedo[1], case.teff_k[1]


def high(case: Case) -> tuple[float, float, float]:
    return case.radius_re[2], case.albedo[2], case.teff_k[2]
