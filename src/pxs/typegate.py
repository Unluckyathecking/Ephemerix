"""Decide whether a spectrum may be typed at all, before a template match is shown.

The classifier (pxs.typing) already refuses poor fits, too few points, ties, grid edges
and spectra with no molecular band, so this gate keeps only what the classifier cannot
see. Reasons to show no type, each with a sentence for the user:
- detected over too narrow a range: fewer than MIN_DETECTED points at S/N >= SNR_DETECTED
  (with the honest binned errors, pxs.binning), or fewer than MIN_ARRAYS of the six
  detector arrays detecting the source. An array detects it when at least
  MIN_ARRAY_FRACTION of its usable points are at S/N >= SNR_DETECTED, so a few noise
  peaks or a few points lit by a neighbour do not count as coverage. Two arrays means at
  least 3.8-5.0 um (D5 and D6, with the CO2 and CO bands and the steep rise of a cold
  brown dwarf); a single array is too narrow for any red shape not to fit.
  Evidence (real combined spectra, this rule): Eps Ind B, DENIS 0255, 2MASS 0559 detect
  on all 6 arrays, 2MASS 0415 on 5; UGPS 0722 (T9) and WISE 0855 (Y4) on D5 and D6
  only, with 1-4 scattered S/N >= 3 points on each shorter array.
  A spectrum that fails this count is still typed, as provisional (`provisional_kind`
  "faint"), only when all of these hold (faint_fit_reason): the fit as a whole is
  significant, detection_sigma >= FAINT_MIN_SIGMA (pxs.typing: the matched-filter S/N of
  the best model over every point, detected one by one or not); its class is "brown dwarf";
  the neighbour checks ran and found nothing, not even a 10-25% neighbour; and the target
  was found in an image. Its range is at least FAINT_HALF_WIDTH subtypes either side
  (pxs.spectra asks the matcher for that).
  Where the two numbers come from: probes/assembly/faint_degrade.py (15 Nov 2026) scales
  the eight gallery targets that pass the count down to S = 5-50 with Gaussian noise from
  three faint fields' errors and scores each range against the published type. The faint
  ones were never used. With the usual floor of 1 subtype 16-19% of the ranges at S = 13-19
  missed it; with a floor of 2, 4.5% at S = 10-16 (47 of 1039, 95% 3.3-6.0%; 2.4% to 11.7%
  by field) and 2.2% over all S. At S = 8-10 it was 9% (bound 16%). Added to real forced
  photometry at 405 empty positions the rate was about 1%. Nothing in these numbers singles
  out 10: it is a judgement, and the one gallery target typed this way passes at any
  threshold from 6 to 12.
  What the threshold cannot do: where unrelated light of 5 sigma or more sits at the
  position (27% of 616 empty positions near the gallery targets; 14% of those the neighbour
  check clears) a third to a half of the types were wrong, at any threshold. Only the class
  call and the catalogue checks guard against that, hence the conditions above. None of
  the 616 empty positions was called a brown dwarf; 31 were called a star or "not a brown
  dwarf" by the fit, which is why those calls are not shown on a faint spectrum.
- blended: a Gaia star comes within one SPHEREx pixel of the target at the SPHEREx epochs
  and is not clearly fainter than it (pxs.blend.blend_blocks_typing), or a brighter CatWISE
  source further out is estimated to add at least 25% of the target's light inside the
  photometry's fitting area (pxs.blend.contamination_gate; CWISE J2021+1524, where a W1 9.1
  star 13" away made the SPHEREx fluxes 6 times the WISE ones at 3.4 and 4.6 um).
- unseen: no WISE or SPHEREx image detected the target, so nothing confirms the forced
  photometry at the predicted position is the target's (UNSEEN_REASON).
A neighbour estimated at 10-25% keeps the type but marks it provisional: the match gets a
`provisional` sentence, also put in the warnings. The 25% level is a judgement made after
seeing which targets each level affects (pxs.blend).
Units: micrometres, mJy.
"""

from __future__ import annotations

from collections.abc import Sequence

from pxs.typing import MIN_POINTS
from pxs.typing.models import valid_range

SNR_DETECTED = 3.0
MIN_DETECTED = 15
MIN_ARRAYS = 2
MIN_ARRAY_FRACTION = 0.5
FAINT_MIN_SIGMA = 10.0  # fit significance needed to type a spectrum that fails the count
FAINT_HALF_WIDTH = 2  # subtypes either side of the best match, at least, for such a type
FAINT_NOTE = ("The object is faint, so this type comes from fitting all of its SPHEREx points "
              "together rather than from clear detections at many wavelengths; treat it as "
              "provisional. Its range is at least two subtypes either side of the best match.")


def detected(spec: dict) -> list[dict]:
    """Unflagged points of a manifest spectrum with flux / err >= SNR_DETECTED."""
    return [p for p in spec["points"] if not p["flagged"] and p["flux"] is not None
            and p["err"] and p["flux"] / p["err"] >= SNR_DETECTED]


def detecting_arrays(spec: dict) -> list[int]:
    """Detector arrays with at least MIN_ARRAY_FRACTION of their usable points detected."""
    usable = [p for p in spec["points"] if not p["flagged"] and p["flux"] is not None
              and p["err"]]
    hits = {id(p) for p in detected(spec)}
    out = []
    for det in sorted({p["detector"] for p in usable if p["detector"] is not None}):
        pts = [p for p in usable if p["detector"] == det]
        if sum(id(p) in hits for p in pts) >= MIN_ARRAY_FRACTION * len(pts):
            out.append(det)
    return out


def faint_reason(spec: dict) -> str | None:
    """A sentence saying why the spectrum is too faint to type, or None when it is not."""
    det = detected(spec)
    arrays = detecting_arrays(spec)
    if len(det) >= MIN_DETECTED and len(arrays) >= MIN_ARRAYS:
        return None
    if not det:
        return "The SPHEREx spectrum has no clear detection, so the object is not classified."
    lo, hi = min(p["wl_um"] for p in det), max(p["wl_um"] for p in det)
    if len(det) >= MIN_DETECTED:  # enough points, but not across enough arrays
        return (f"SPHEREx detects the object clearly in only {len(arrays)} of its six wavelength "
                f"ranges ({len(det)} clear points, {lo:.1f} to {hi:.1f} µm), which is too "
                "little of the spectrum to classify it.")
    return (f"SPHEREx detects the object at only {len(det)} wavelengths ({lo:.1f} to "
            f"{hi:.1f} µm), which is too little of the spectrum to classify it.")


FAINT_UNCHECKED = ("The spectrum is not classified because the object is faint and the checks "
                   "for light from neighbouring sources could not be run (a catalogue did not "
                   "answer, or the target has no catalogued brightness to compare with).")
FAINT_NEIGHBOUR = ("The spectrum is not classified because the object is faint and a catalogued "
                   "source nearby may supply a tenth or more of the light measured.")


def neighbours_checked(target, catwise: Sequence[dict] | None, gaia_failed: bool) -> bool:
    """True when both neighbour checks could really be made for `target`: the Gaia and
    CatWISE lists arrived (`catwise` is None when its query failed) and the target has a W1
    or W2 magnitude, without which pxs.blend cannot estimate a neighbour's share."""
    return (catwise is not None and not gaia_failed
            and (target.w1_mag is not None or target.w2_mag is not None))


def faint_fit_reason(match: dict, count_reason: str, caution: str | None = None,
                     checked: bool = True) -> str | None:
    """For a spectrum that fails the count (`count_reason`, from faint_reason) and that
    nothing else withholds: None when its fit may be shown as a provisional type, else the
    sentence saying why not. Only a significant fit called "brown dwarf" is shown, and only
    when the neighbour checks ran and found nothing (`caution` is a 10-25% neighbour). The
    match must have been made with a range floor of FAINT_HALF_WIDTH (pxs.spectra does)."""
    if (match.get("detection_sigma") or 0.0) < FAINT_MIN_SIGMA:
        return count_reason
    if match.get("class") != "brown dwarf":
        return ("The spectrum is not classified because the object is faint and a fit to all "
                "of its points together does not show a clear brown dwarf. "
                f"{match.get('verdict', '')}").rstrip()
    if not checked:
        return FAINT_UNCHECKED
    return FAINT_NEIGHBOUR if caution else None


def too_few_reason(spectra: Sequence[dict]) -> str | None:
    """Why no match was attempted on the spectrum that would be typed (the last one: the
    combined spectrum when there are several passes), or None when that is not the cause."""
    if not spectra:
        return None
    lo, hi = valid_range()
    n = sum(1 for p in spectra[-1]["points"] if not p["flagged"] and p["flux"] is not None
            and p["err"] and lo <= p["wl_um"] <= hi)
    if n >= MIN_POINTS:
        return None
    return (f"The spectrum is not classified because only {n} of its points between {lo:.1f} "
            f"and {hi:.1f} µm are usable, and at least {MIN_POINTS} are needed to compare it "
            "with the templates.")


BLEND_REASON = ("The spectrum is not classified because a Gaia star comes within one SPHEREx "
                "pixel of the target and is not clearly fainter than it, so it may supply "
                "much of the light at some wavelengths.")


UNSEEN_REASON = ("The spectrum is not classified because the target was not found in any "
                 "WISE or SPHEREx image, so nothing confirms that the light measured at its "
                 "predicted position is the target's.")


def vet(match: dict | None, spectra: Sequence[dict], blended: bool,
        contaminated: str | None = None, seen: bool = True, caution: str | None = None,
        checked: bool = True) -> tuple[dict | None, list[str]]:
    """(match or None, sentences for the manifest warnings). Never changes `match` itself.
    `contaminated` is the sentence from blend.contamination_reason, when there is one; `seen`
    is False when no image detected the target (the spectrum is forced photometry at the
    predicted position, which nothing then confirms). `caution`
    (blend.contamination_caution) keeps the match of a spectrum that passes the count, as
    `provisional` with `provisional_kind` "neighbour". `checked` (neighbours_checked) is False
    when the neighbour checks could not be made.

    A spectrum that fails the count is withheld with the stronger reasons first (unseen,
    blended, contaminated) and the count sentence last. With none of those it is typed only
    under faint_fit_reason, as `provisional` with `provisional_kind` "faint". With no match
    at all, the reason is that too few points are usable."""
    if match is None:
        return None, [r for r in (too_few_reason(spectra),) if r]
    spec = next(s for s in spectra if s["id"] == match["spectrum_id"])
    count = faint_reason(spec)
    reasons = [r for r in (UNSEEN_REASON if not seen else None,
                           BLEND_REASON if blended else None, contaminated) if r]
    if reasons:
        return None, [*reasons, *([count] if count else [])]
    if count:
        why = faint_fit_reason(match, count, caution, checked)
        if why:
            return None, [why]
        return {**match, "provisional": FAINT_NOTE, "provisional_kind": "faint"}, [FAINT_NOTE]
    if caution:
        return {**match, "provisional": caution, "provisional_kind": "neighbour"}, [caution]
    return match, []
