"""Bands, band means and AB magnitudes.

Bands are top-hats in wavelength, an approximation to the real response:
- SPHEREx detector bands 1-6, edges from Hui et al. 2026 (ApJS 284, 10; arXiv:2602.09139),
  Table 1. Each band holds about 17 of the 102 spectral channels (R = 35-130).
- WISE W1 and W2: isophotal wavelength +/- half the width from Jarrett et al. 2011 (ApJ 735,
  112, Table 1: 3.35 um / 0.66 um and 4.60 um / 1.04 um). W2's red edge is cut at 5.09 um,
  where the solar table ends (5.12 um nominal; the response there is low).
Vega-to-AB offsets for WISE: Explanatory Supplement sec. 4.4h, Table 3 (W1 2.699, W2 3.339).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

AB_ZERO_UJY = 3631e6
N_SAMPLES = 300


@dataclass(frozen=True)
class Band:
    name: str
    lo_um: float
    hi_um: float
    vega_to_ab: float = 0.0  # m_AB = m_Vega + vega_to_ab (WISE only)

    @property
    def mid_um(self) -> float:
        return 0.5 * (self.lo_um + self.hi_um)


SPHEREX_BANDS: tuple[Band, ...] = (
    Band("SPHEREx D1", 0.75, 1.11),
    Band("SPHEREx D2", 1.11, 1.64),
    Band("SPHEREx D3", 1.64, 2.42),
    Band("SPHEREx D4", 2.42, 3.82),
    Band("SPHEREx D5", 3.82, 4.42),
    Band("SPHEREx D6", 4.42, 5.00),
)
WISE_BANDS: tuple[Band, ...] = (
    Band("WISE W1", 3.02, 3.68, 2.699),
    Band("WISE W2", 4.08, 5.09, 3.339),
)
ALL_BANDS = SPHEREX_BANDS + WISE_BANDS
CHANNELS_PER_SPHEREX_BAND = 17  # 102 channels / 6 detectors


def band_mean(f: Callable[[float], float], band: Band, n: int = N_SAMPLES) -> float:
    """Mean of f(wavelength um) over the band (midpoint rule, uniform in wavelength)."""
    step = (band.hi_um - band.lo_um) / n
    return sum(f(band.lo_um + (i + 0.5) * step) for i in range(n)) / n


def ab_mag(ujy: float) -> float:
    """AB magnitude of a flux density in microjansky."""
    if ujy <= 0:
        return math.inf
    return -2.5 * math.log10(ujy / AB_ZERO_UJY)


def ujy_from_ab(mag: float) -> float:
    return AB_ZERO_UJY * 10 ** (-0.4 * mag)
