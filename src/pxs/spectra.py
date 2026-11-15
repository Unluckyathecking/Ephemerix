"""Per-pass SPHEREx spectra, a combined "all" spectrum, and the template match.

Units: wavelengths and bandwidths in micrometres, fluxes and errors in mJy (F_nu).

The combined spectrum bins all passes on a grid matched to SPHEREx resolution: one bin
per channel width, R = 40 below 3.8 um and R = 120 above. Each bin is the
inverse-variance mean of its unflagged points (flux = sum(w f) / sum(w), w = 1 / err^2),
with error max(1 / sqrt(sum(w)), the bin's own scatter, the empty-position noise) (see
pxs.binning: frames are not independent and bright ones scatter beyond their errors).
Flagged points are kept in the per-pass spectra as `flagged: true` and never enter a
mean; a bin with only flagged points becomes one flagged point with no flux.

The match types the combined spectrum whenever there are two or more passes (see
build_all), and each pass is also typed on its own to check that they agree.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pxs.astrometry import decimal_year
from pxs.binning import corrected, make_bin, usable
from pxs.sources import SpecPoint
from pxs.typegate import FAINT_HALF_WIDTH, detected, faint_reason
from pxs.typing import load_templates, match_spectrum
from pxs.typing.decide import RANGE_MIN_HALF_WIDTH

R_SHORT, R_LONG, R_SPLIT_UM = 40.0, 120.0, 3.8
ALL_ID = "spx-all"
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _num(v) -> float | None:
    return float(v) if v is not None and math.isfinite(float(v)) else None


def _usable(p: SpecPoint) -> bool:
    return usable(p)


def _point(wl, bw, flux, err, detector, flagged) -> dict:
    r = lambda v: None if v is None else round(float(v), 6)
    return {"wl_um": r(wl), "bw_um": r(bw), "flux": r(flux), "err": r(err),
            "detector": None if detector is None else int(detector), "flagged": bool(flagged)}


def iso_date(mjd: float) -> str:
    """ISO 8601 UTC date-time of an MJD, to the second."""
    t = np.datetime64("1858-11-17T00:00:00") + np.timedelta64(round(mjd * 86400), "s")
    return f"{t}Z"


def _label(mjd: float) -> str:
    t = np.datetime64("1858-11-17") + np.timedelta64(int(mjd), "D")
    year, month = str(t)[:4], int(str(t)[5:7])
    return f"{_MONTHS[month - 1]} {year}"


def pass_spectrum(points: Sequence[SpecPoint], spec_id: str) -> dict:
    """Manifest spectrum for one pass, every point carried through, sorted by wavelength."""
    mjds = [p.mjd for p in points]
    pts = [
        _point(p.wl_um, p.bw_um, _num(p.flux_mjy), _num(p.err_mjy), p.detector,
               not _usable(p))
        for p in sorted(points, key=lambda p: p.wl_um)
    ]
    return {"id": spec_id, "label": _label(min(mjds)), "date_start": iso_date(min(mjds)),
            "date_end": iso_date(max(mjds)), "unit": "mJy", "points": pts}


def bin_edges(wl_min: float, wl_max: float) -> np.ndarray:
    """Bin edges covering [wl_min, wl_max], each bin lambda / R wide (R 40 or 120)."""
    edges = [wl_min]
    while edges[-1] <= wl_max:
        lam = edges[-1]
        edges.append(lam * (1.0 + 1.0 / (R_SHORT if lam < R_SPLIT_UM else R_LONG)))
    return np.array(edges)


def combined_spectrum(passes: Sequence[Sequence[SpecPoint]]) -> dict:
    """Inverse-variance mean of all passes in resolution-matched wavelength bins."""
    allp = [p for ps in passes for p in ps]
    wls = np.array([p.wl_um for p in allp])
    edges = bin_edges(float(wls.min()), float(wls.max()))
    idx = np.searchsorted(edges, wls, side="right") - 1
    bins = [make_bin([p for p, k in zip(allp, idx) if k == b], edges[b], edges[b + 1])
            for b in sorted(set(idx.tolist()))]
    pts = [_point(b.wl_um, b.bw_um, b.flux, b.err, b.detector, b.flux is None)
           for b in corrected(bins)]
    mjds = [p.mjd for p in allp]
    label = f"All passes, {_label(min(mjds))} to {_label(max(mjds))}"
    return {"id": ALL_ID, "label": label, "date_start": iso_date(min(mjds)),
            "date_end": iso_date(max(mjds)), "unit": "mJy", "points": pts}


def pass_ids(passes: Sequence[Sequence[SpecPoint]]) -> list[str]:
    """Ids like "spx-2025b": year of the pass start and its order within that year."""
    years = [int(decimal_year(min(p.mjd for p in ps))) for ps in passes]
    seen: Counter = Counter()
    out = []
    for y in years:
        out.append(f"spx-{y}{chr(ord('a') + seen[y])}")
        seen[y] += 1
    return out


def _fit(spec: dict, pairs: bool, half_width: int) -> dict | None:
    pts = [p for p in spec["points"] if p["flux"] is not None and p["err"] is not None]
    if not pts:
        return None
    m = match_spectrum([p["wl_um"] for p in pts], [p["flux"] for p in pts],
                       [p["err"] for p in pts], [p["flagged"] for p in pts], pairs=pairs,
                       min_half_width=half_width)
    return None if m is None else {"spectrum_id": spec["id"], **m}


def _match(spec: dict, pairs: bool = True) -> dict | None:
    return _fit(spec, pairs, RANGE_MIN_HALF_WIDTH)


def _own_match(spec: dict) -> dict | None:
    """The match of the spectrum chosen for typing. One that fails the count gate gets the
    wider type range a faint spectrum needs (pxs.typegate, which then decides if it is shown)."""
    return _match(spec) if faint_reason(spec) is None else _fit(spec, True, FAINT_HALF_WIDTH)


def _typeable(spec: dict, match: dict | None) -> bool:
    """A match exists and the spectrum passes the S/N gate (pxs.typegate)."""
    return match is not None and faint_reason(spec) is None


def _fallback(pass_specs: Sequence[dict]) -> tuple[dict, dict] | None:
    """(spectrum, match) of the single pass with most clear detections that passes the gate."""
    for spec in sorted(pass_specs, key=lambda s: -len(detected(s))):
        m = _match(spec)
        if _typeable(spec, m):
            return spec, m
    return None


@dataclass(frozen=True)
class PassMatch:
    """Class and best type of one pass's own spectrum, or why it was not typed."""

    spectrum_id: str
    typed: bool
    klass: str | None = None
    best: str | None = None
    type_range: tuple[str, str] | None = None
    reason: str = ""  # why not typed

    def as_dict(self) -> dict:
        return {"spectrum_id": self.spectrum_id, "typed": self.typed, "class": self.klass,
                "best": self.best,
                "type_range": None if self.type_range is None else list(self.type_range),
                "reason": self.reason}


@dataclass(frozen=True)
class PassAgreement:
    """Do the passes, typed one by one, agree with the match?

    status: "agree" (every typed pass has the match's class and, for brown dwarfs, a best
    type inside the match's type range), "disagree", or "too few" (fewer than two passes
    could be typed). Passes that fail the gate are "not typed", never a disagreement.
    """

    status: str
    passes: tuple[PassMatch, ...]
    sentence: str

    def as_dict(self) -> dict:
        return {"status": self.status, "sentence": self.sentence,
                "passes": [p.as_dict() for p in self.passes]}


def pass_match(spec: dict) -> PassMatch:
    """Type one pass's spectrum on its own (no pair test), through the S/N gate."""
    reason = faint_reason(spec)
    m = None if reason else _match(spec, pairs=False)
    if m is None:
        return PassMatch(spec["id"], False, reason=reason or "too few clean points")
    rng = m.get("type_range")
    return PassMatch(spec["id"], True, m["class"], m["best"]["type"],
                     None if rng is None else (rng[0], rng[1]))


def _agrees(p: PassMatch, match: dict) -> bool:
    if p.klass != match["class"]:
        return False
    rng = match.get("type_range")
    if match["class"] != "brown dwarf" or not rng:
        return True
    labels = list(load_templates())
    return labels.index(rng[0]) <= labels.index(p.best) <= labels.index(rng[1])


def agreement(pass_specs: Sequence[dict], match: dict | None) -> PassAgreement | None:
    """Per-pass consistency of `match` (None when there is no match to check)."""
    if match is None:
        return None
    pm = tuple(pass_match(s) for s in pass_specs)
    typed = [p for p in pm if p.typed]
    if len(typed) < 2:
        return PassAgreement("too few", pm, f"Only {len(typed)} of {len(pm)} SPHEREx "
                             "passes can be typed on their own, so they cannot be compared.")
    bad = [p for p in typed if not _agrees(p, match)]
    if not bad:
        n = len(typed)
        tail = "" if n == len(pm) else f" ({len(pm) - n} too faint to type alone)"
        return PassAgreement("agree", pm, f"All {n} passes typed on their own agree{tail}.")
    parts = ", ".join(f"{p.spectrum_id}: {p.klass}, {p.best}" for p in bad)
    return PassAgreement("disagree", pm, f"{len(bad)} of {len(typed)} passes typed on their "
                         f"own disagree with the combined result ({parts}).")


def pass_checks(agreement: PassAgreement, spectra: Sequence[dict]) -> dict:
    """`match.per_pass` and `match.pass_agreement` (docs/api.md) from a PassAgreement."""
    labels = {s["id"]: s["label"] for s in spectra}
    per_pass = [{"id": p.spectrum_id, "label": labels.get(p.spectrum_id, p.spectrum_id),
                 "typed": p.typed, "class": p.klass, "type": p.best,
                 "type_range": None if p.type_range is None else list(p.type_range),
                 "reason": p.reason} for p in agreement.passes]
    return {"per_pass": per_pass,
            "pass_agreement": {"status": agreement.status, "sentence": agreement.sentence}}


@dataclass(frozen=True)
class Spectra:
    """Manifest spectra, the match, and the per-pass consistency check."""

    spectra: list[dict]
    match: dict | None
    agreement: PassAgreement | None


def chosen_match(spectra: Sequence[dict]) -> dict | None:
    """The match of manifest `spectra` (passes in time order, then "all" if more than one).

    With one pass, that pass. With two or more, the combined spectrum (it averages every
    pass and carries errors measured on the data, pxs.binning); only when it fails the S/N
    gate or gives no match, the single pass with the most clear detections that passes. If
    none passes, the combined spectrum's match is kept, made with the wider type range of a
    faint spectrum, and the build's gate (pxs.typegate.vet) shows it as provisional or
    withholds it with a reason.
    """
    if not spectra:
        return None
    match = _own_match(spectra[-1])
    if len(spectra) > 1 and not _typeable(spectra[-1], match):
        alt = _fallback(spectra[:-1])
        match = alt[1] if alt else match
    return match


def build_all(passes: Sequence[Sequence[SpecPoint]], check_passes: bool = True) -> Spectra:
    """Spectra (passes in time order, then "all" if more than one), match (chosen_match) and
    the per-pass agreement."""
    # A pass with no usable point (e.g. every frame saturated) has nothing to plot; the
    # build's warnings say why, so it gets no spectrum entry.
    passes = sorted((ps for ps in passes if any(_usable(p) for p in ps)),
                    key=lambda ps: min(p.mjd for p in ps))
    if not passes:
        return Spectra([], None, None)
    spectra = [pass_spectrum(ps, i) for ps, i in zip(passes, pass_ids(passes))]
    if len(passes) == 1:
        return Spectra(spectra, chosen_match(spectra), None)
    per_pass = list(spectra)
    spectra.append(combined_spectrum(passes))
    match = chosen_match(spectra)
    return Spectra(spectra, match, agreement(per_pass, match) if check_passes else None)


def build_spectra(passes: Sequence[Sequence[SpecPoint]]) -> tuple[list[dict], dict | None]:
    """Manifest `spectra` and `match` (see build_all; no per-pass check)."""
    out = build_all(passes, check_passes=False)
    return out.spectra, out.match
