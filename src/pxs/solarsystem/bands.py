"""Ice band depths from a reflectance spectrum: in-band over continuum ratios with errors.

Each band is the inverse-variance mean reflectance in its window divided by that in the
continuum window CONT_UM (0.75-1.30 um, short of the strong H2O and CH4 ice bands; it
holds only weak CH4 features at 0.89, 1.0 and 1.16 um). Depth = 1 - ratio. A single
shared continuum is deliberately simple: it ignores any slope, so on a red or blue
surface a "depth" partly measures the slope.

At SPHEREx resolution (R about 40) the water- and methane-ice bands overlap, so windows
are named by wavelength, with the ice that dominates there. The 1.7 um window also takes
the crystalline H2O band at 1.65 um, and the 3.3 um window sits inside the broad H2O
absorption that spans 2.8-3.5 um. What separates the two ices is the pattern: water ice
is deep at 2.0 um and much shallower at 2.3 um; methane ice is deep at 2.3 um.

Windows (um) and the detectors that feed them: continuum 0.75-1.30 (D1, D2),
1.5: 1.48-1.60 (D2), 1.7: 1.66-1.76 (D3), 2.0: 1.95-2.10 (D3), 2.3: 2.28-2.40 (D3),
3.0: 2.90-3.15 (D4), 3.3: 3.20-3.40 (D4). Ratios across detectors carry any
detector-to-detector calibration offset (not measured here).

Saturated bands: where the ice absorbs almost all light (Haumea at 3.0 um) the in-band
flux is zero within its noise, so the measured ratio scatters about 0 and can fall below
it, which would print a depth above 100%. When the ratio is not above zero at 2 sigma the
band is reported as saturated with a 95% lower limit on its depth,
depth_min = 1 - (max(ratio, 0) + 1.645 err): the ratio is clamped at zero first so a
downward fluctuation earns no extra depth.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .solar import NORM_WINDOW_UM, RPoint

CONT_UM = NORM_WINDOW_UM
WINDOWS: dict[str, tuple[float, float]] = {
    "1.5 um (H2O)": (1.48, 1.60),
    "1.7 um (CH4; H2O 1.65)": (1.66, 1.76),
    "2.0 um (H2O)": (1.95, 2.10),
    "2.3 um (CH4)": (2.28, 2.40),
    "3.0 um (H2O)": (2.90, 3.15),
    "3.3 um (CH4; H2O wing)": (3.20, 3.40),
}
DETECT_SIGMA = 3.0
CLIP_SIGMA = 5.0
SATURATED_SIGMA = 2.0  # band flux not above zero at this many sigma: saturated
Z95_ONE_SIDED = 1.645


@dataclass(frozen=True)
class Depth:
    """Band ratio (in-band / continuum reflectance) and depth = 1 - ratio, with errors."""

    label: str
    window_um: tuple[float, float]
    n_band: int
    n_cont: int
    ratio: float
    err: float

    @property
    def depth(self) -> float:
        return 1.0 - self.ratio

    @property
    def sigma(self) -> float:
        return self.depth / self.err if self.err > 0 else math.nan

    @property
    def detected(self) -> bool:
        return math.isfinite(self.sigma) and self.sigma >= DETECT_SIGMA

    @property
    def saturated(self) -> bool:
        """In-band flux not above zero at SATURATED_SIGMA: only a lower limit on the depth."""
        return math.isfinite(self.ratio) and self.ratio < SATURATED_SIGMA * self.err

    @property
    def depth_min(self) -> float | None:
        """95% one-sided lower limit on the depth of a saturated band (None otherwise)."""
        if not self.saturated:
            return None
        return max(0.0, 1.0 - (max(self.ratio, 0.0) + Z95_ONE_SIDED * self.err))

    def text(self) -> str:
        """"<label> 61% +- 5%", or for a saturated band "<label> saturated, deeper than 83%"."""
        if self.saturated:
            return f"{self.label} saturated, deeper than {self.depth_min:.0%} (95% confidence)"
        return f"{self.label} {self.depth:.0%} +- {self.err:.0%}"

    def to_dict(self) -> dict:
        ok = math.isfinite(self.ratio)
        r = lambda v: round(v, 3) if ok and v is not None else None
        return {"label": self.label, "wl_um": list(self.window_um), "n_band": self.n_band,
                "n_continuum": self.n_cont, "ratio": r(self.ratio),
                "depth": None if self.saturated else r(self.depth),
                "depth_min": r(self.depth_min), "saturated": self.saturated,
                "err": r(self.err), "sigma": round(self.sigma, 1) if ok else None,
                "detected": self.detected}


def _mean(pts: Sequence[RPoint], lo: float, hi: float) -> tuple[float, float, int]:
    """Inverse-variance mean in [lo, hi), after a 5-sigma robust clip when n >= 4."""
    use = [p for p in pts if lo <= p.wl_um < hi and p.err > 0 and math.isfinite(p.refl)]
    if len(use) >= 4:
        v = np.array([p.refl for p in use])
        med = float(np.median(v))
        mad = 1.4826 * float(np.median(np.abs(v - med)))
        use = [p for p in use if abs(p.refl - med) <= CLIP_SIGMA * max(mad, p.err)]
    if not use:
        return math.nan, math.nan, 0
    w = np.array([1 / p.err**2 for p in use])
    v = np.array([p.refl for p in use])
    return float(np.sum(w * v) / w.sum()), float(1 / math.sqrt(w.sum())), len(use)


def band_depths(pts: Sequence[RPoint], windows: dict[str, tuple[float, float]] = WINDOWS
                ) -> list[Depth]:
    """One Depth per window; NaN ratio when the band or the continuum has no points."""
    c, ce, nc = _mean(pts, *CONT_UM)
    out = []
    for label, (lo, hi) in windows.items():
        b, be, nb = _mean(pts, lo, hi)
        if nb == 0 or nc == 0 or not c > 0:
            out.append(Depth(label, (lo, hi), nb, nc, math.nan, math.nan))
            continue
        err = math.hypot(be / c, b * ce / c**2)
        out.append(Depth(label, (lo, hi), nb, nc, b / c, err))
    return out


def _by(depths: Sequence[Depth], prefix: str) -> Depth | None:
    return next((d for d in depths if d.label.startswith(prefix) and math.isfinite(d.ratio)),
                None)


def ice_pattern(depths: Sequence[Depth]) -> str:
    """"water ice", "methane ice" or "" from the 2.0 vs 2.3 um depths (2-sigma apart)."""
    d20, d23 = _by(depths, "2.0"), _by(depths, "2.3")
    if d20 is None or d23 is None:
        return ""
    diff, err = d20.depth - d23.depth, math.hypot(d20.err, d23.err)
    if d20.detected and diff > 2 * err:
        return "water ice"
    if d23.detected and -diff > 2 * err:
        return "methane ice"
    return ""


def reading(depths: Sequence[Depth], published: str) -> str:
    """Plain sentences: which bands SPHEREx sees, the ice pattern, and what is published."""
    seen = [d for d in depths if d.detected]
    pub = f" Published: {published.rstrip('.')}." if published else ""
    if not seen:
        weak = [d for d in depths if math.isfinite(d.sigma) and 2.0 <= d.sigma < DETECT_SIGMA]
        tail = (f" Hints (2-3 sigma) at {', '.join(d.label for d in weak)}." if weak else "")
        return f"No absorption band is detected at {DETECT_SIGMA:g} sigma in these data.{tail}{pub}"
    parts = [d.text() for d in seen]
    lo, hi = CONT_UM
    s = (f"SPHEREx sees absorption at {'; '.join(parts)} (depth against the {lo:g}-{hi:g} um "
         "continuum).")
    pat = ice_pattern(depths)
    if pat == "water ice":
        s += " Deep at 2.0 um and shallower at 2.3 um: the pattern of water ice."
    elif pat == "methane ice":
        s += " Deeper at 2.3 um than at 2.0 um: the pattern of methane ice."
    return s + pub
