"""Fit every model family to a cleaned spectrum on one common set of points.

Units: wavelengths in micrometres, fluxes and errors in mJy (F_nu); chi2 is
dimensionless. Points are first fitted with every single-component model; when at least
DROP_MIN_POINTS are usable, the N_DROP worst points of the best of those fits are dropped
for every model alike (so no model can shed the points that condemn it), and all models
are refitted.

Families are compared with the Bayesian information criterion on rescaled chi2:
score = chi2 / s2 + k ln n, where k is the family's number of free parameters and
s2 = max(1, smallest reduced chi2 of any family). Rescaling by s2 makes the comparison
robust to error bars that are uniformly too small; BIC (rather than AIC) is used because
the flexible comparison families must not win on noise and the margin we need grows with n.

Written with Claude Code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import models as mdl
from .fit import fit_one, fit_two, noise_scale, worst_points

N_DROP = 5
DROP_MIN_POINTS = 25


@dataclass(frozen=True)
class Candidate:
    """Best fit of one model. curve(wl_um) gives the scaled model in mJy at any wavelength."""

    label: str
    family: str  # "brown dwarf", "star", "dust", "power law", "star + dust"
    chi2: float
    n_params: int
    curve: Callable[[np.ndarray], np.ndarray]
    # (type,) | (T K, A_V mag, chi2 with A_V = 0) | (alpha,)
    # | (T_star K, A_V mag, T_dust K, dust share at 4.5 um)
    params: tuple = ()


@dataclass(frozen=True)
class Analysis:
    """Everything fitted: data actually used, template fits and the best comparison per family."""

    wl: np.ndarray
    d: np.ndarray
    sigma: np.ndarray
    n_used: int
    templates: tuple[Candidate, ...]  # the 24 types, in M..Y order
    others: tuple[Candidate, ...]  # best "star", "dust", "power law", "star + dust"
    s2: float  # error rescaling factor, >= 1
    eta: float  # white-noise scale of the best model's residuals

    def score(self, c: Candidate) -> float:
        """BIC on rescaled chi2: chi2 / s2 + k ln n (dimensionless)."""
        return c.chi2 / self.s2 + c.n_params * np.log(self.n_used)

    def rchi2(self, c: Candidate) -> float:
        """Reduced chi2 of a candidate with its own number of parameters."""
        return c.chi2 / max(self.n_used - c.n_params, 1)


def _fnu_curve(make: Callable[[np.ndarray], np.ndarray], scale: float):
    return lambda wl: scale * make(np.asarray(wl, dtype=float))


def _template_curve(label: str, scale: float):
    m = mdl.load_templates()[label]
    return lambda wl: scale * np.interp(wl, m.wl_um, m.flam) * np.asarray(wl) ** 2


@lru_cache(maxsize=4)
def _shapes_cached(wl_key: bytes) -> dict:
    wl = np.frombuffer(wl_key)
    return {"templates": mdl.template_shapes(wl), "bb": mdl.blackbody_shapes(wl),
            "pl": mdl.power_law_shapes(wl), "combo": mdl.combo_shapes(wl)}


def _shapes(wl: np.ndarray) -> dict:
    return _shapes_cached(np.ascontiguousarray(wl, dtype=float).tobytes())


def _first_pass_keep(sh: dict, d: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Points kept for every model: all, or all but the N_DROP worst of the best single fit."""
    if d.size < DROP_MIN_POINTS:
        return np.ones(d.shape, dtype=bool)
    w = 1.0 / sigma**2
    stack = np.vstack([sh["templates"][1], sh["bb"][1], sh["pl"][1]])
    s, chi2 = fit_one(stack, d, w)
    i = int(np.argmin(chi2))
    return worst_points((d - s[i] * stack[i]) / sigma, N_DROP)


def _template_fits(sh: dict, d, w, keep) -> tuple[Candidate, ...]:
    labels, shapes = sh["templates"]
    s, chi2 = fit_one(shapes[:, keep], d[keep], w[keep])
    return tuple(Candidate(lab, "brown dwarf", float(c), mdl.N_PARAMS["brown dwarf"],
                           _template_curve(lab, float(k)), (lab,))
                 for lab, k, c in zip(labels, s, chi2))


def _blackbody_fits(sh: dict, d, w, keep) -> list[Candidate]:
    """Best "star" (>= 2500 K) and best "dust" (< 2500 K) reddened blackbody.

    params are (T K, A_V mag, chi2 of the best unreddened blackbody of the same family).
    """
    params, shapes = sh["bb"]
    s, chi2 = fit_one(shapes[:, keep], d[keep], w[keep])
    temps = np.array([p[0] for p in params])
    unreddened = np.array([p[1] == 0.0 for p in params])
    out = []
    for family, sel in (("star", temps >= mdl.STAR_MIN_K), ("dust", temps < mdl.STAR_MIN_K)):
        idx = np.flatnonzero(sel)
        i = int(idx[np.argmin(chi2[idx])])
        chi2_av0 = float(chi2[np.flatnonzero(sel & unreddened)].min())
        t, av = params[i]
        curve = _fnu_curve(lambda wl, t=t, av=av: mdl.bb_fnu(wl, t, av), float(s[i]))
        out.append(Candidate(mdl.blackbody_label(t, av), family, float(chi2[i]),
                             mdl.N_PARAMS["blackbody"], curve, (t, av, chi2_av0)))
    return out


def _power_law_fits(sh: dict, d, w, keep) -> Candidate:
    alphas, shapes = sh["pl"]
    s, chi2 = fit_one(shapes[:, keep], d[keep], w[keep])
    i = int(np.argmin(chi2))
    a = alphas[i]
    return Candidate(mdl.power_law_label(a), "power law", float(chi2[i]),
                     mdl.N_PARAMS["power law"],
                     _fnu_curve(lambda wl, a=a: mdl.power_law_fnu(wl, a), float(s[i])), (a,))


def _combo_fits(sh: dict, d, w, keep) -> Candidate:
    params, star, dust = sh["combo"]
    sa, sb, chi2 = fit_two(star[:, keep], dust[:, keep], d[keep], w[keep])
    i = int(np.argmin(chi2))
    t, av, td = params[i]
    a, b = float(sa[i]), float(sb[i])

    def curve(wl):
        return a * mdl.bb_fnu(wl, t, av) + b * mdl.bb_fnu(wl, td, 0.0)

    at = np.array([4.5])
    total = float(curve(at)[0])
    dust_share = float(b * mdl.bb_fnu(at, td, 0.0)[0] / total) if total > 0 else 0.0
    return Candidate(mdl.combo_label(t, av, td), "star + dust", float(chi2[i]),
                     mdl.N_PARAMS["star + dust"], curve, (t, av, td, dust_share))


def analyse(wl: np.ndarray, d: np.ndarray, sigma: np.ndarray) -> Analysis:
    """Fit every family to (wl um, d mJy, sigma mJy), already cleaned. Inputs are not modified."""
    sh = _shapes(wl)
    keep = _first_pass_keep(sh, d, sigma)
    w = 1.0 / sigma**2
    templates = _template_fits(sh, d, w, keep)
    others = (*_blackbody_fits(sh, d, w, keep), _power_law_fits(sh, d, w, keep),
              _combo_fits(sh, d, w, keep))
    n = int(keep.sum())
    allc = (*templates, *others)
    s2 = max(1.0, min(c.chi2 / max(n - c.n_params, 1) for c in allc))
    best = min(allc, key=lambda c: c.chi2)
    eta = noise_scale(((d - best.curve(wl)) / sigma)[keep])
    return Analysis(wl[keep], d[keep], sigma[keep], n, templates, others, s2, eta)


def detection_sigma(a: Analysis) -> float:
    """Significance of the best model against no source at all (dimensionless).

    sqrt(chi2 of zero flux - smallest chi2 of any model) on the points used. For a model
    with one free scale this is the matched-filter signal-to-noise of its amplitude, so it
    adds up every point, including those that are not detected one by one.
    """
    chi0 = float(np.sum((a.d / a.sigma) ** 2))
    best = min(c.chi2 for c in (*a.templates, *a.others))
    return float(np.sqrt(max(chi0 - best, 0.0)))
