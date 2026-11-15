"""Model spectra: SPIFF brown-dwarf templates and analytic comparison families.

Units: wavelengths in micrometres, temperatures in kelvin, extinction in magnitudes.
Templates are F_lambda in arbitrary units; every shape handed to the fitter is an
F_nu shape (F_nu ~ F_lambda * lambda^2) with arbitrary normalisation.

Comparison families (all analytic, no external data):
- "blackbody": Planck curves 300-10000 K with interstellar reddening A_V 0-20 mag.
  Hot ones (>= 2500 K) are stars; cool ones are dust or other red sources.
- "power law": F_nu ~ lambda^alpha, alpha -2 to 4 (flat and rising: young stellar
  objects with discs, quasars).
- "star + dust": a reddened 2500-10000 K star plus a 300-1500 K blackbody, both with
  non-negative scales (a T Tauri star with a warm disc).

Extinction law: A_lambda = A_V * 0.112 * (lambda / 2.2 um)^-1.7, a power law with the
near-infrared index of Martin & Whittet (1990) normalised to A_K / A_V = 0.112 of
Rieke & Lebofsky (1985, ApJ 288, 618). Past about 3 um the real law flattens, so this
underestimates extinction there; the grid still spans the observed colours.

Written with Claude Code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "data" / "templates" / "spiff"
TYPE_LETTERS = "MLTY"

_HC_OVER_K_UM_K = 14387.77  # h c / k_B in micrometre kelvin
_FIELD_TYPE = re.compile(r"^([MLTY]\d)_spherex_standard\.csv$")

AK_OVER_AV = 0.112  # Rieke & Lebofsky 1985
EXT_INDEX = 1.7  # A_lambda ~ lambda^-1.7 in the near infrared
STAR_MIN_K = 2500.0  # blackbodies at or above this are "stars"

BB_TEMPS_K = tuple(float(t) for t in np.round(np.geomspace(300.0, 10000.0, 48)))
BB_AV = tuple(float(a) for a in np.arange(0.0, 20.01, 0.5))
PL_ALPHA = tuple(float(a) for a in np.round(np.arange(-2.0, 4.001, 0.1), 2))
COMBO_STAR_K = (2500.0, 3000.0, 3500.0, 4000.0, 5000.0, 6000.0, 8000.0, 10000.0)
COMBO_AV = (0.0, 2.0, 5.0, 10.0, 15.0, 20.0)
COMBO_DUST_K = (300.0, 400.0, 500.0, 600.0, 800.0, 1000.0, 1200.0, 1500.0)

# Free parameters per family, for the information criterion (the scale counts as one).
N_PARAMS = {"brown dwarf": 2, "blackbody": 3, "power law": 2, "star + dust": 5}


@dataclass(frozen=True)
class Model:
    """One template: F_lambda (arbitrary units) on a wavelength grid (um)."""

    label: str
    wl_um: np.ndarray
    flam: np.ndarray
    is_star: bool = False


def type_index(label: str) -> int:
    """Position of a template type in the M8 ... Y1 sequence counted in subtypes (M8 = 0)."""
    return 10 * TYPE_LETTERS.index(label[0]) + int(label[1]) - 8


def _read_template(path: Path, label: str) -> Model:
    data = np.genfromtxt(path, delimiter=",", skip_header=1)
    good = np.isfinite(data).all(axis=1) & (data[:, 1] > 0)
    wl, flam = data[good, 0].copy(), data[good, 1].copy()
    wl.flags.writeable = False
    flam.flags.writeable = False
    return Model(label, wl, flam)


@lru_cache(maxsize=1)
def _templates() -> dict[str, Model]:
    found = {}
    for path in TEMPLATE_DIR.glob("*.csv"):
        m = _FIELD_TYPE.match(path.name)
        if m:
            found[m.group(1)] = _read_template(path, m.group(1))
    if not found:
        raise FileNotFoundError(f"no SPIFF templates found in {TEMPLATE_DIR}")
    return {k: found[k] for k in sorted(found, key=type_index)}


def load_templates() -> dict[str, Model]:
    """Field-gravity SPIFF templates (M8 to Y1), keyed by spectral type, ordered M to Y.

    Low-gravity and subdwarf templates are vendored but not used for typing.
    """
    return dict(_templates())


def valid_range() -> tuple[float, float]:
    """(min, max) wavelength in um covered by every template; nothing is extrapolated."""
    t = _templates().values()
    return max(m.wl_um[0] for m in t), min(m.wl_um[-1] for m in t)


def blackbody(wl_um: np.ndarray, temp_k: float) -> np.ndarray:
    """Planck F_lambda (arbitrary units, equal to 1 at 2 um) for a blackbody of temp_k kelvin."""

    def raw(w: np.ndarray) -> np.ndarray:
        return np.asarray(w, dtype=float) ** -5 / np.expm1(_HC_OVER_K_UM_K / (w * temp_k))

    return raw(np.asarray(wl_um, dtype=float)) / raw(np.array(2.0))


def extinction_mag(wl_um: np.ndarray, av_mag: float) -> np.ndarray:
    """A_lambda in magnitudes at wl_um for visual extinction av_mag (power law, see module doc)."""
    return av_mag * AK_OVER_AV * (np.asarray(wl_um, dtype=float) / 2.2) ** -EXT_INDEX


def bb_fnu(wl_um: np.ndarray, temp_k: float, av_mag: float) -> np.ndarray:
    """Reddened blackbody as an F_nu shape (arbitrary units, fixed normalisation at 2 um)."""
    wl = np.asarray(wl_um, dtype=float)
    return blackbody(wl, temp_k) * (wl / 2.0) ** 2 * 10 ** (-0.4 * extinction_mag(wl, av_mag))


def power_law_fnu(wl_um: np.ndarray, alpha: float) -> np.ndarray:
    """F_nu ~ lambda^alpha, equal to 1 at 2 um."""
    return (np.asarray(wl_um, dtype=float) / 2.0) ** alpha


def template_shapes(wl: np.ndarray) -> tuple[list[str], np.ndarray]:
    """Template labels and their F_nu shapes at wl (um), one row per template."""
    t = _templates()
    rows = [np.interp(wl, m.wl_um, m.flam) * wl**2 for m in t.values()]
    return list(t), np.array(rows)


def blackbody_shapes(wl: np.ndarray) -> tuple[list[tuple[float, float]], np.ndarray]:
    """(T in K, A_V in mag) for each reddened blackbody and the F_nu shapes at wl (um)."""
    params = [(t, a) for t in BB_TEMPS_K for a in BB_AV]
    return params, np.array([bb_fnu(wl, t, a) for t, a in params])


def power_law_shapes(wl: np.ndarray) -> tuple[list[float], np.ndarray]:
    """Index alpha of each F_nu ~ lambda^alpha and the shapes at wl (um), equal to 1 at 2 um."""
    return list(PL_ALPHA), np.array([power_law_fnu(wl, a) for a in PL_ALPHA])


def combo_shapes(wl: np.ndarray) -> tuple[list[tuple[float, float, float]], np.ndarray, np.ndarray]:
    """(T_star K, A_V mag, T_dust K) and the two F_nu components at wl for star + dust models."""
    params = [(t, a, d) for t in COMBO_STAR_K for a in COMBO_AV for d in COMBO_DUST_K]
    star = np.array([bb_fnu(wl, t, a) for t, a, _ in params])
    dust = np.array([bb_fnu(wl, d, 0.0) for _, _, d in params])
    return params, star, dust


def blackbody_label(temp_k: float, av_mag: float) -> str:
    """Label of a reddened blackbody; star labels start with "star" (see docs/api.md)."""
    base = f"{temp_k:.0f} K" if av_mag < 0.25 else f"{temp_k:.0f} K, A_V {av_mag:g}"
    return f"star ({base})" if temp_k >= STAR_MIN_K else f"dust ({base})"


def power_law_label(alpha: float) -> str:
    """Label of an F_nu power law."""
    return f"power law (F_nu ~ lambda^{alpha:+.1f})"


def combo_label(star_k: float, av_mag: float, dust_k: float) -> str:
    """Label of a star + dust model. It must not begin with "star": the page reads a label
    beginning with "star" as "not a brown dwarf", and a cold-dust fit can be a brown dwarf
    colder than the grid."""
    red = "" if av_mag == 0 else f", A_V {av_mag:g}"
    return f"dust + star (dust {dust_k:.0f} K; star {star_k:.0f} K{red})"
