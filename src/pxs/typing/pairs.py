"""Unresolved-pair test: is the spectrum better fitted by two brown-dwarf templates?

Every pair of field templates (276) is fitted with two non-negative scales. The pair is
compared not with a bare single template but with a single template times a free colour
tilt, lambda^beta with |beta| <= 0.6: a real dwarf redder or bluer than the median
template is otherwise "fitted better" by two templates (a tilt of +-0.3 gave false pairs in
about half of noiseless trials). A pair is reported when all of these hold:
- it beats the best tilted single template by at least PAIR_MIN_DELTA in rescaled chi2
  (chi2 / s2, s2 = max(1, the tilted single's reduced chi2)); the pair has one more free
  parameter than a tilted single (4 against 3), so this is a BIC margin of
  PAIR_MIN_DELTA - ln n;
- the two types differ by at least PAIR_MIN_GAP subtypes;
- the fainter component makes up at least PAIR_MIN_SHARE of the model flux at some
  wavelength in the data.
Units: wavelengths um, fluxes mJy.

Written with Claude Code.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .core import Analysis
from .fit import fit_one, fit_two
from .models import template_shapes, type_index

PAIR_MIN_DELTA = 25.0
PAIR_MIN_GAP = 3
PAIR_MIN_SHARE = 0.2
TILTS = tuple(float(b) for b in np.round(np.arange(-0.6, 0.601, 0.05), 2))


@dataclass(frozen=True)
class Pair:
    """Best two-template fit and its gain over the best tilted single template."""

    types: tuple[str, str]  # warmer first
    chi2: float
    delta_vs_single: float  # rescaled chi2 of best tilted single minus that of the pair
    share: float  # largest flux fraction of the fainter component, 0-1
    reported: bool
    scales: tuple[float, float] = (0.0, 0.0)  # of the two template shapes, as fitted

    def curve(self, wl: np.ndarray) -> np.ndarray:
        """The fitted pair model in mJy at wavelengths `wl` (um)."""
        labels, shapes = template_shapes(np.asarray(wl, dtype=float))
        i, j = labels.index(self.types[0]), labels.index(self.types[1])
        return self.scales[0] * shapes[i] + self.scales[1] * shapes[j]


def tilted_single_chi2(shapes: np.ndarray, wl: np.ndarray, d: np.ndarray,
                       w: np.ndarray) -> float:
    """Smallest chi2 of any template (rows of shapes) times (wl / 2 um)^beta, beta in TILTS."""
    tilted = np.vstack([shapes * (wl / 2.0) ** b for b in TILTS])
    return float(fit_one(tilted, d, w)[1].min())


def best_pair(a: Analysis) -> Pair:
    """Fit all template pairs to the analysed spectrum and test the best one."""
    labels, shapes = template_shapes(a.wl)
    w = 1.0 / a.sigma**2
    idx = np.array(list(combinations(range(len(labels)), 2)))
    sa, sb, chi2 = fit_two(shapes[idx[:, 0]], shapes[idx[:, 1]], a.d, w)
    k = int(np.argmin(chi2))
    i, j = idx[k]
    single = tilted_single_chi2(shapes, a.wl, a.d, w)
    s2 = max(1.0, single / max(a.n_used - 3, 1))
    comp_a, comp_b = sa[k] * shapes[i], sb[k] * shapes[j]
    total = comp_a + comp_b
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.nan_to_num(np.minimum(comp_a, comp_b) / total)
    delta = (single - float(chi2[k])) / s2
    types = (labels[i], labels[j])
    reported = bool(delta >= PAIR_MIN_DELTA and min(sa[k], sb[k]) > 0
                    and abs(type_index(types[0]) - type_index(types[1])) >= PAIR_MIN_GAP
                    and float(share.max()) >= PAIR_MIN_SHARE)
    return Pair(types, float(chi2[k]), float(delta), float(share.max()), reported,
                (float(sa[k]), float(sb[k])))
