"""Class call, confidence, type range and the verdict sentence.

Scores are BIC on rescaled chi2 (see core.py), dimensionless; a lower score is better.

Decision, in order:
1. Fewer than LOW_POINTS usable points: "uncertain", too few to classify.
2. Goodness-of-fit gate on g = (smallest reduced chi2 of any model) / max(1, eta^2), where
   eta is the white-noise scale measured from neighbouring residuals (so g does not grow
   when the error bars are uniformly too small). g > GATE_HARD: nothing fits, "uncertain".
   GATE_RCHI2 < g <= GATE_HARD: a poor fit; a call needs margin >= HIGH_MARGIN and is at
   most "medium" confidence.
3. margin = best comparison score - best template score.
   margin >= CLASS_MARGIN: a brown dwarf, if the best template is L0 or later and at least
   one molecular band the template predicts is detected; M8 or M9 is "uncertain" (the
   templates start at M8, so an ordinary late-M star cannot be excluded); no band seen is
   "uncertain".
   margin <= -CLASS_MARGIN: "star" when the best comparison is a star (reddened or not),
   otherwise "not a brown dwarf" - unless the source may be a brown dwarf colder than the
   coldest template (see looks_colder_than_grid; WISE 0855, Y4, fits a 400 K dust model
   better than Y1), in which case the call is "uncertain".
   Otherwise "uncertain".

Written with Claude Code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .core import Analysis, Candidate
from .features import Band, measure_bands
from .models import load_templates, type_index

LOW_POINTS = 15
GATE_RCHI2 = 3.0  # Gagne et al. flag reduced chi2 above 3 as peculiar
GATE_HARD = 10.0  # above this nothing is called
CLASS_MARGIN = 10.0  # BIC difference: "very strong" (Kass & Raftery 1995)
HIGH_MARGIN = 30.0
RANGE_DELTA = 4.0  # delta chi2 for the type range, after rescaling
RANGE_MIN_HALF_WIDTH = 1  # subtypes either side of the best, at least
# Below this fitted A_V a star is not called reddened: two nearby (57-79 pc, unreddened)
# M dwarfs fitted A_V 0-3.5 because their molecular bands bend the blackbody shape.
REDDENED_MIN_AV = 4.0
WARM_EDGE = ("M8", "M9")
COLD_EDGE = ("Y0", "Y1")
COLD_K = 600.0  # a comparison this cold may be a brown dwarf beyond the grid (Y0 is ~450 K)
COLD_ALPHA = 3.0


@dataclass(frozen=True)
class Decision:
    """The class call and everything needed to explain it."""

    klass: str  # "brown dwarf" | "star" | "not a brown dwarf" | "uncertain"
    reason: str  # "fit", "few points", "no fit", "tie", "warm edge", "cold edge", "no bands"
    margin: float  # best comparison score minus best template score
    gate_rchi2: float  # best reduced chi2 / max(1, eta^2)
    best_template: Candidate
    best_other: Candidate
    bands: tuple[Band, ...]
    reddened: bool  # best star has A_V >= REDDENED_MIN_AV and A_V = 0 is worse by > ln n


def decide(a: Analysis) -> Decision:
    """Class call for an analysed spectrum (see module docstring)."""
    bd = min(a.templates, key=a.score)
    other = min(a.others, key=a.score)
    margin = a.score(other) - a.score(bd)
    best = min((*a.templates, *a.others), key=a.rchi2)
    gate = a.rchi2(best) / max(1.0, a.eta**2)
    bands = tuple(measure_bands(a.wl, a.d, a.sigma * np.sqrt(a.s2), bd.curve(a.wl)))
    klass, reason = _class(a.n_used, gate, margin, bd, other, bands)
    reddened = bool(other.family == "star" and other.params[1] >= REDDENED_MIN_AV
                    and (other.params[2] - other.chi2) / a.s2 > np.log(a.n_used))
    return Decision(klass, reason, float(margin), float(gate), bd, other, bands, reddened)


def looks_colder_than_grid(bd: Candidate, other: Candidate) -> bool:
    """True when a winning comparison could be a brown dwarf colder than Y1.

    That is: the comparison is not a plain or reddened star, and either the best template
    is already Y0 or Y1, or the comparison's 4.5 um flux comes mostly from something at
    COLD_K or colder (a dust blackbody, the dust part of a star + dust model) or from a
    power law at least as steep as lambda^3.
    """
    if other.family == "star":
        return False
    if bd.label in COLD_EDGE:
        return True
    p = other.params
    if other.family == "dust":
        return p[0] <= COLD_K
    if other.family == "star + dust":
        return p[2] <= COLD_K and p[3] >= 0.5
    if other.family == "power law":
        return p[0] >= COLD_ALPHA
    return False


def _class(n, gate, margin, bd, other, bands) -> tuple[str, str]:
    if n < LOW_POINTS:
        return "uncertain", "few points"
    min_margin = HIGH_MARGIN if gate > GATE_RCHI2 else CLASS_MARGIN
    if gate > GATE_HARD:
        return "uncertain", "no fit"
    if margin >= min_margin:
        if bd.label in WARM_EDGE:
            return "uncertain", "warm edge"
        if not any(b.detected for b in bands):
            return "uncertain", "no bands"
        return "brown dwarf", "fit"
    if margin <= -min_margin:
        if looks_colder_than_grid(bd, other):
            return "uncertain", "cold edge"
        return ("star", "fit") if other.family == "star" else ("not a brown dwarf", "fit")
    return "uncertain", "no fit" if gate > GATE_RCHI2 else "tie"


def confidence(dec: Decision) -> str:
    """Confidence in the class call: "high", "medium" or "low"."""
    if dec.klass == "uncertain":
        return "low"
    if dec.gate_rchi2 > GATE_RCHI2:
        return "medium"
    return "high" if abs(dec.margin) >= HIGH_MARGIN else "medium"


def type_range(a: Analysis,
               min_half_width: int = RANGE_MIN_HALF_WIDTH) -> tuple[list[str], bool, bool]:
    """([earliest, latest] template types, open at the warm end, open at the cold end).

    Templates within RANGE_DELTA * max(1, best reduced chi2) of the best template's chi2,
    taken as one contiguous span in the M-L-T-Y sequence, then widened to at least
    `min_half_width` subtypes either side of the best. An end is open when it is the
    edge of the template grid (M8 or Y1): the object may be warmer or colder.
    """
    labels = list(load_templates())
    chi2 = {c.label: c.chi2 for c in a.templates}
    best = min(chi2, key=chi2.get)
    scale = max(1.0, chi2[best] / max(a.n_used - 2, 1))
    near = [lab for lab in labels if chi2[lab] <= chi2[best] + RANGE_DELTA * scale]
    i_best = labels.index(best)
    lo = min(labels.index(near[0]), i_best - min_half_width)
    hi = max(labels.index(near[-1]), i_best + min_half_width)
    lo, hi = max(lo, 0), min(hi, len(labels) - 1)
    return [labels[lo], labels[hi]], lo == 0, hi == len(labels) - 1


def describe(label: str) -> str:
    """Plain words for a template type."""
    letter, num = label[0], int(label[1])
    if letter == "M":
        return "a very low-mass object at the star and brown dwarf boundary"
    if letter == "L":
        return "a warm brown dwarf"
    if letter == "Y":
        return "a very cold brown dwarf"
    return "a cold brown dwarf" if num >= 6 else "a brown dwarf"


def span_text(rng: list[str], open_warm: bool, open_cold: bool) -> str:
    """"T6 to T8", "T9 or colder", "M9 or warmer" or "L0 to L2"."""
    lo, hi = rng
    if open_cold and not open_warm:
        return f"{lo} or colder"
    if open_warm and not open_cold:
        return f"{hi} or warmer"
    return lo if lo == hi else f"{lo} to {hi}"


def other_words(dec: Decision) -> str:
    """Plain words for the best comparison model."""
    if dec.best_other.family == "star":
        return "a star dimmed and reddened by dust" if dec.reddened else "an ordinary star"
    return "a dusty or young red source"


def verdict(dec: Decision, rng, open_warm: bool, open_cold: bool) -> str:
    """One plain sentence for a newcomer."""
    bd = dec.best_template.label
    if dec.reason == "few points":
        return "Too few clean measurements to classify."
    if dec.reason == "no fit":
        return ("Does not look like any brown-dwarf template or any of the comparison spectra "
                "(stars, reddened stars, dusty sources), so it is left unclassified.")
    if dec.reason == "tie":
        return (f"Could be a brown dwarf (best match {bd}) or {other_words(dec)}; "
                "the data cannot tell.")
    if dec.reason == "warm edge":
        return (f"Looks like a late-M object at the star and brown dwarf boundary, type "
                f"{span_text(rng, open_warm, open_cold)} (best match {bd}); the templates start "
                "at M8, so it may be an ordinary star.")
    if dec.reason == "no bands":
        return (f"Fits a brown-dwarf template best ({bd}), but none of its molecular bands is "
                "clearly detected, so it is left unclassified.")
    if dec.reason == "cold edge":
        return ("Rises steeply towards 5 microns like a very cold source: it may be a brown "
                "dwarf colder than the coldest template (Y1) or a dusty source, and these data "
                "cannot tell.")
    poor = dec.gate_rchi2 > GATE_RCHI2
    if dec.klass in ("star", "not a brown dwarf"):
        words = other_words(dec) if dec.klass == "star" else "a dusty or young red source"
        tail = ", though nothing fits it closely." if poor else "."
        return f"Looks like {words}, not a brown dwarf{tail}"
    lead = "Most like" if poor else "Consistent with"
    tail = ", though no template fits it closely." if poor else "."
    if bd == "Y1":
        return f"{lead} a very cold brown dwarf, type Y1 or colder (the coldest template){tail}"
    return (f"{lead} {describe(bd)}, type {span_text(rng, open_warm, open_cold)} "
            f"(best match {bd}){tail}")


def subtype_gap(a: str, b: str) -> int:
    """Number of subtypes between two template types."""
    return abs(type_index(a) - type_index(b))
