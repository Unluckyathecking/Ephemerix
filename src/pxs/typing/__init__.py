"""Spectral typing of a SPHEREx spectrum, with the right to refuse.

Units: wavelengths in micrometres, data fluxes in mJy (F_nu). Every model returned is
scaled to the data, in mJy.

The spectrum is fitted with the 24 SPIFF field brown-dwarf templates (M8-Y1; Gagné et
al., arXiv:2604.22012) and with families of things that are not brown dwarfs: reddened
blackbodies 300-10000 K (stars, and dust below 2500 K), F_nu power laws, and a reddened
star plus warm dust. Errors get a 10% floor; the 5 worst points of the best fit are
dropped for every model alike. Families are compared by BIC on chi2 rescaled by the best
reduced chi2 (so mis-scaled errors do not decide the call). A "brown dwarf" needs to beat
every comparison family clearly, pass a goodness-of-fit gate that is itself robust to
mis-scaled errors, and show at least one molecular band its template predicts. See
decide.py for the rules and docs/api.md for the output.

Written with Claude Code.
"""

from __future__ import annotations

import logging

import numpy as np

from .core import Analysis, Candidate, analyse, detection_sigma
from .decide import RANGE_MIN_HALF_WIDTH, confidence, decide, type_range, verdict
from .models import blackbody, load_templates, valid_range
from .pairs import Pair, best_pair

__all__ = ["FEATURES", "blackbody", "load_templates", "match_spectrum"]

log = logging.getLogger(__name__)

ERROR_FLOOR = 0.10  # fractional error floor on each flux
MIN_POINTS = 8  # below this, no match is attempted
_METHOD = (
    "Chi-square fits of the SPIFF brown-dwarf templates (Gagné et al., arXiv:2604.22012) "
    "and of non-brown-dwarf comparisons (reddened stars, dust, power laws, star plus dust), "
    "compared by an information criterion on rescaled chi-square, with a goodness-of-fit "
    "gate and a check that the template's molecular bands are actually seen."
)

# Molecular bands to shade on the spectrum plot: label and wavelength window (um).
FEATURES: list[dict] = [
    {"label": "H2O", "wl_um": [1.33, 1.50]},
    {"label": "CH4", "wl_um": [1.55, 1.75]},
    {"label": "H2O", "wl_um": [1.75, 2.05]},
    {"label": "CH4", "wl_um": [2.10, 2.40]},
    {"label": "CO", "wl_um": [2.29, 2.40]},
    {"label": "H2O", "wl_um": [2.55, 2.95]},
    {"label": "CH4", "wl_um": [3.10, 3.60]},
    {"label": "CO2", "wl_um": [4.20, 4.35]},
    {"label": "CO", "wl_um": [4.50, 4.80]},
]


def _clean(wl, flux, err, flagged):
    """Return (wl, flux, sigma) of usable points: finite, unflagged, inside the template range."""
    wl, flux, err = (np.asarray(a, dtype=float) for a in (wl, flux, err))
    if not wl.shape == flux.shape == err.shape or wl.ndim != 1:
        raise ValueError("wl_um, flux_mjy and err_mjy must be 1-D arrays of the same length")
    bad = np.zeros(wl.shape, dtype=bool) if flagged is None else np.asarray(flagged, dtype=bool)
    if bad.shape != wl.shape:
        raise ValueError("flagged must have the same length as the spectrum")
    lo, hi = valid_range()
    with np.errstate(invalid="ignore"):
        sigma = np.maximum(err, ERROR_FLOOR * np.abs(flux))
        ok = (
            np.isfinite(wl) & np.isfinite(flux) & np.isfinite(sigma) & (err >= 0)
            & ~bad & (sigma > 0) & (wl >= lo) & (wl <= hi)
        )
    order = np.argsort(wl[ok], kind="stable")
    return wl[ok][order], flux[ok][order], sigma[ok][order]


def _r(x: float) -> float:
    return float(f"{x:.4g}")


def _curve_points(c: Candidate | Pair) -> list[list[float]]:
    wl = next(iter(load_templates().values())).wl_um
    return [[round(float(a), 4), _r(float(b))] for a, b in zip(wl, c.curve(wl))]


def _fit_entry(a: Analysis, c: Candidate) -> dict:
    return {"type": c.label, "chi2": round(c.chi2, 2), "dof": a.n_used - c.n_params}


def _reported_pair(a: Analysis, klass: str, pairs: bool) -> Pair | None:
    if not pairs or klass != "brown dwarf":
        return None
    p = best_pair(a)
    log.debug("best pair %s delta %.1f share %.2f", p.types, p.delta_vs_single, p.share)
    return p if p.reported else None


def _pair_key(p: Pair) -> str:
    """Key of the pair's curve in `models`, e.g. "T1 + T6"."""
    return " + ".join(p.types)


def _pair_block(p: Pair | None) -> dict | None:
    if p is None:
        return None
    return {"types": list(p.types), "chi2": round(p.chi2, 2),
            "delta_vs_single": round(p.delta_vs_single, 2), "model": _pair_key(p)}


def _models(best: Candidate, runner: Candidate, pair: Pair | None) -> dict:
    """Curves of the best and runner-up fits, and of the reported pair if any."""
    out = {c.label: _curve_points(c) for c in (best, runner)}
    if pair is not None:
        out[_pair_key(pair)] = _curve_points(pair)
    return out


def _verdict_with_pair(text: str, pair: dict | None) -> str:
    if pair is None:
        return text
    t1, t2 = pair["types"]
    return (f"Fits better as two brown dwarfs blended together (about {t1} and {t2}) "
            "than as one.")


def match_spectrum(wl_um, flux_mjy, err_mjy, flagged=None, pairs: bool = True,
                   min_half_width: int = RANGE_MIN_HALF_WIDTH) -> dict | None:
    """Classify a spectrum and type it against the SPIFF templates, or refuse to.

    Args:
        wl_um: channel wavelengths, micrometres.
        flux_mjy: F_nu in mJy.
        err_mjy: 1-sigma errors in mJy.
        flagged: optional boolean array; True points are ignored.
        pairs: run the unresolved-pair test (only when the class is "brown dwarf").
        min_half_width: the type range spans at least this many subtypes either side of
            the best template (pxs.typegate asks for 2 on faint spectra).

    Points that are flagged, non-finite, or outside the template range (1.007 to
    4.967 um; nothing is extrapolated) are dropped, and each error is floored at 10% of
    the flux. Returns the `match` block of docs/api.md without `spectrum_id` (the caller
    adds it), or None when fewer than 8 points are usable. The inputs are not modified.
    """
    wl, d, sigma = _clean(wl_um, flux_mjy, err_mjy, flagged)
    if wl.size < MIN_POINTS:
        return None
    a = analyse(wl, d, sigma)
    dec = decide(a)
    ranked = sorted((*a.templates, *a.others), key=a.score)
    best, runner = ranked[0], ranked[1]
    is_bd_side = dec.klass in ("brown dwarf", "uncertain")
    rng, open_warm, open_cold = type_range(a, min_half_width)
    found = _reported_pair(a, dec.klass, pairs)
    pair = _pair_block(found)
    return {
        "best": _fit_entry(a, best),
        "runner_up": _fit_entry(a, runner),
        "delta_chi2": round(a.score(runner) - a.score(best), 2),
        "verdict": _verdict_with_pair(verdict(dec, rng, open_warm, open_cold), pair),
        "confidence": confidence(dec),
        "class": dec.klass,
        "type_range": rng if is_bd_side else None,
        "range_open_warm": bool(is_bd_side and open_warm),
        "range_open_cold": bool(is_bd_side and open_cold),
        "delta_class": round(abs(dec.margin), 2),
        "detection_sigma": round(detection_sigma(a), 1),
        "pair": pair,
        "bands_detected": [b.name for b in dec.bands if b.detected],
        "candidates": [{"type": c.label, "family": c.family, "chi2": round(c.chi2, 2),
                        "score": round(a.score(c), 2)} for c in ranked],
        "models": _models(best, runner, found),
        "method": _METHOD,
    }
