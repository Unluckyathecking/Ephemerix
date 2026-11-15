"""The pass rules: motion against the catalogue, tool type range against the published type."""

import math
import re

MOTION_SIGMA = 3.0  # both components must be within this many stated sigma
# A catalogue motion smaller than this many times our largest stated error cannot be told from
# zero by our measurement: agreement then shows we measure no false motion, not that we confirm it.
WEAK_TEST_FACTOR = 3.0

PASS, FAIL, REFUSED, NOT_APPLICABLE = "pass", "fail", "refused", "not_applicable"

THRESHOLDS = {
    "motion": f"Both proper-motion components within {MOTION_SIGMA:g} sigma of the catalogue, "
              "sigma being the error we state for that component. No percentage "
              "allowance: it would forgive large errors on fast movers.",
    "type": "Our spectral-type range contains the published type. For an unresolved "
            "pair, any one published component inside the range counts. Where we say "
            "\"not a brown dwarf\" and gives no range, agreement with a published star or giant "
            "is a pass and disagreement with a published L, T or Y type is a fail.",
    "refused": "We had a spectrum but left it unclassified. Shown with its own reason; "
               "neither a pass nor a fail.",
    "provisional": "We gave a type but warned that a catalogued neighbour may add 10-25% "
                   "of the light (at 25% or more the spectrum is left unclassified). The type is "
                   "still scored against the published one; the row is flagged and counted. These "
                   "two limits were chosen after seeing which targets each level affected. "
                   "A second kind is counted apart from the other types: an object too faint to "
                   "detect at many wavelengths one by one is typed only when a fit to all of its "
                   "points together is at least 10 times the noise and is called a brown dwarf, "
                   "the neighbour checks ran and found nothing, and the object is seen in an "
                   "image. Its range is at least two subtypes either side. That limit and that "
                   "width were chosen after tests on fainter copies of the eight brighter "
                   "targets, not on the faint ones.",
    "weak_test": f"Where the catalogue's total motion is smaller than {WEAK_TEST_FACTOR:g} times our "
                 "stated error, a pass is marked a weak test: it shows we measure no false "
                 "motion, but it cannot confirm the catalogue's. Such rows still count as passes.",
    "all_frames": "Where no single image shows the object clearly enough to measure its "
                  "position, the motion is fitted on all W2 images at once and scored by the "
                  "same rule. Such a row counts images, not detections, and says so.",
    "not_applicable": "The check cannot be made: no motion measured (target not detected), no "
                      "published proper motion, no usable spectrum, no parsable published type, "
                      "or no stated error.",
}

# Notes the data cannot derive. Each is shown beside the verdict and never changes it.
EXPLANATIONS = {
    ("epsilon-indi-b", "motion"): (
        "Likely explanation: Gaia DR3 gives this unresolved pair a poor single-star fit (RUWE "
        "4.30, data/targets.json) and its 34-month motion includes the pair's orbital motion "
        "(the two brown dwarfs orbit each other every 11 years, Chen et al. 2022, "
        "arXiv:2205.08077). With that orbit, a fit over Gaia's 34 months can be off by up to "
        "about 100 mas/yr in declination, depending on where in the orbit it falls; over our "
        "16 years, about one and a half orbits, by a few. It is still scored against Gaia and "
        "it still counts as a mismatch."
    ),
    ("cwise-1055-5443", "motion"): (
        "Partly explained. CatWISE J105512.19+544339.0 (W2 15.0, the target 14.4) sits 10-13 "
        "arcsec north of the target from 2010 to 2019 and pulled the fitted positions north. "
        "Fitting that source together with the target moves the declination motion from "
        "-262.7 to -252.6 mas/yr: about 10 of the 40 mas/yr. The rest is not explained. No "
        "other source lies under the target's 2010-2016 path (nothing above 4% of its "
        "brightness in the 2021-2024 images), and fitting all 23 W2 images at once gives "
        "-247.5 +- 14.6 mas/yr. Kirkpatrick et al. 2021 give the total motion to 2.9 mas/yr. "
        "It still counts as a mismatch."
    ),
}

ALL_FRAMES = "all_frames"  # measured_motion.method (pxs.trackmotion)
ALL_FRAMES_NOTE = (
    "No single image shows this object clearly enough to measure its position, so there are "
    "no detections to count. The motion comes from fitting all {n} W2 images at once: one "
    "source moving in a straight line, with its brightness, starting position and motion as "
    "the only free numbers, and the catalogued neighbours in the model."
)


def all_frames_note(motion: dict) -> str | None:
    """The note for a row whose motion was fitted on all frames at once, else None."""
    if motion.get("method") != ALL_FRAMES:
        return None
    return ALL_FRAMES_NOTE.format(n=motion.get("n_frames") or "the")


def second_reference(measured: dict | None, ref: dict | None) -> dict | None:
    """A second published motion shown beside the verdict; it never changes the verdict.
    `ref`: data/targets.json `pm_second_reference` (pmra_masyr, pmdec_masyr, source, caveat).
    """
    m = motion_check(measured, ref)
    if not ref or m["sigma"] is None:
        return None
    d, s = m["diff"], m["sigma"]
    text = (f"{ref['source']}: {ref['pmra_masyr']:g}, {ref['pmdec_masyr']:g} mas/yr. The "
            f"measured motion differs from it by {d['pmra']:+.1f} and {d['pmdec']:+.1f} mas/yr, "
            f"{s['pmra']:.1f} and {s['pmdec']:.1f} sigma. {ref['caveat']}")
    return {"source": ref["source"], "pmra": ref["pmra_masyr"], "pmdec": ref["pmdec_masyr"],
            "diff": {"pmra": d["pmra"], "pmdec": d["pmdec"]}, "sigma": s, "text": text}

NOT_BD = "not a brown dwarf"
UNCERTAIN = "uncertain"  # the fit could not say what the object is: never scored as a type
NEIGHBOUR, FAINT = "neighbour", "faint"  # match.provisional_kind (pxs.typegate.vet)
# Published text that names a star or giant rather than a brown dwarf (RW Aurigae, R Draconis).
_STELLAR = re.compile(r"\b(star|giant)\b", re.IGNORECASE)
_BASE = {"M": -10, "L": 0, "T": 10, "Y": 20}
_NUM = r"(\d+(?:\.\d+)?)"
_COMPONENT = re.compile(rf"\s*(?:d/sd|esd|sd|d)?([MLTY]){_NUM}(?:\s*[-–]\s*[MLTY]?{_NUM})?")


def subtype_value(label: str) -> float | None:
    """One spectral type on a single axis (M0 = -10, L0 = 0, T0 = 10, Y0 = 20), or None."""
    parsed = parse_published(label)
    return None if parsed is None else parsed[0][0]


def parse_published(text: str) -> list[tuple[float, float]] | None:
    """Published type text as (low, high) subtype intervals, one per component, or None.

    "T1-1.5 + T6 (unresolved pair)" gives [(11, 11.5), (16, 16)]; "M4 star" gives [(-6, -6)].
    """
    out: list[tuple[float, float]] = []
    for part in text.split("+"):
        m = _COMPONENT.match(part)
        if not m:
            return None
        low = _BASE[m.group(1)] + float(m.group(2))
        high = _BASE[m.group(1)] + float(m.group(3)) if m.group(3) else low
        out.append((min(low, high), max(low, high)))
    return out or None


def _pct(diff: float, ref: float) -> float | None:
    return None if ref == 0 else 100.0 * diff / abs(ref)


def _get(d: dict | None, key: str):
    v = (d or {}).get(key)
    return v if isinstance(v, int | float) else None


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def motion_check(measured: dict | None, catalogue: dict | None,
                 missing_reason: str | None = None) -> dict:
    """Compare measured motion (manifest `measured_motion`) with catalogue pmra/pmdec.

    Either side may be missing; the row keeps the same keys (values None) and the verdict is
    not applicable. `missing_reason` is the manifest's own account of why nothing was measured.
    """
    measured = measured or {}
    err = {
        "pmra": measured.get("err_pmra_masyr") or measured.get("err_masyr"),
        "pmdec": measured.get("err_pmdec_masyr") or measured.get("err_masyr"),
    }
    cat = {"pmra": _get(catalogue, "pmra_masyr"), "pmdec": _get(catalogue, "pmdec_masyr")}
    meas = {"pmra": _get(measured, "pmra_masyr"), "pmdec": _get(measured, "pmdec_masyr")}
    diff = {k: _sub(meas[k], cat[k]) for k in cat}

    def total(v: dict) -> float | None:
        return None if v["pmra"] is None or v["pmdec"] is None else math.hypot(v["pmra"], v["pmdec"])

    total_cat, total_meas = total(cat), total(meas)
    d_total = _sub(total_meas, total_cat)
    row = {
        "catalogue": {**cat, "total_arcsec_yr": None if total_cat is None else total_cat / 1000,
                      "source": (catalogue or {}).get("source")},
        "measured": {**meas, "total_arcsec_yr": None if total_meas is None else total_meas / 1000},
        "diff": {**diff, "total": d_total,
                 "pmra_pct": None if diff["pmra"] is None else _pct(diff["pmra"], cat["pmra"]),
                 "pmdec_pct": None if diff["pmdec"] is None else _pct(diff["pmdec"], cat["pmdec"]),
                 "total_pct": None if d_total is None else _pct(d_total, total_cat)},
        "err_masyr": err,
        "baseline_years": measured.get("baseline_years"),
        "n_detections": measured.get("n_detections"),
        "method": measured.get("method"),  # "all_frames" or None (from single detections)
        "n_frames": measured.get("n_frames"),
        "reduced_chi2": measured.get("reduced_chi2"),
        "parallax_model": measured.get("parallax_model"),
    }

    def na(reason: str) -> dict:
        return {**row, "verdict": NOT_APPLICABLE, "sigma": None, "reason": reason, "weak_test": None}

    if meas["pmra"] is None or meas["pmdec"] is None:
        return na(missing_reason or "Fewer than two detections, so no motion was measured.")
    if cat["pmra"] is None or cat["pmdec"] is None:
        return na("No published proper motion to compare with.")
    if not all(isinstance(e, int | float) and e > 0 for e in err.values()):
        return na("no stated motion error")
    sigma = {k: abs(diff[k]) / err[k] for k in diff}
    worst = max(sigma.values())
    return {**row, "sigma": {**sigma, "max": worst}, "reason": None,
            "verdict": PASS if worst <= MOTION_SIGMA else FAIL,
            "weak_test": weak_test(total_cat, max(err.values()))}


def weak_test(total_cat: float | None, err: float) -> bool | None:
    """True when the catalogue motion is below WEAK_TEST_FACTOR times our error (THRESHOLDS)."""
    return None if total_cat is None else total_cat < WEAK_TEST_FACTOR * err


def _range_bounds(match: dict) -> tuple[float, float] | None:
    r = match.get("type_range")
    if not r:
        return None
    warm, cold = subtype_value(r[0]), subtype_value(r[1])
    if warm is None or cold is None:
        return None
    return (-math.inf if match.get("range_open_warm") else warm,
            math.inf if match.get("range_open_cold") else cold)


def type_check(match: dict | None, published: str | None, has_spectrum: bool,
               reason: str | None) -> dict:
    """Verdict for the spectral type. `reason` is the manifest's own words, when it gave any."""
    provisional = None if match is None else match.get("provisional")
    # Manifests built before `provisional_kind` existed carry only the neighbour kind.
    kind = (match.get("provisional_kind") or NEIGHBOUR) if provisional else None
    row = {"published": published, "best": None, "range": None, "pair": None,
           "exact": None, "reason": reason, "provisional": provisional,
           "provisional_kind": kind}
    if match is None:
        verdict = REFUSED if has_spectrum else NOT_APPLICABLE
        fallback = ("A spectrum was measured, but we gave no classification and no reason for it."
                    if has_spectrum else "There is no SPHEREx spectrum to classify.")
        return {**row, "verdict": verdict, "reason": reason or fallback}
    best = (match.get("best") or {}).get("type")
    pair = (match.get("pair") or {}).get("types")
    row = {**row, "best": best, "range": match.get("type_range"), "pair": pair,
           "range_open_warm": bool(match.get("range_open_warm")),
           "range_open_cold": bool(match.get("range_open_cold")),
           "class": match.get("class"), "confidence": match.get("confidence")}
    if match.get("class") == UNCERTAIN:
        return {**row, "verdict": REFUSED,
                "reason": reason or "The fit could not tell what kind of object this is, so the "
                                    "spectrum is left unclassified."}
    bounds = _range_bounds(match)
    parts = parse_published(published) if published else None
    if match.get("class") == NOT_BD and bounds is None:
        return _class_check(row, published, parts)
    if bounds is None or parts is None:
        return {**row, "verdict": NOT_APPLICABLE,
                "reason": "The published type or our range could not be read."}
    inside = any(bounds[0] <= lo and hi <= bounds[1] for lo, hi in parts)
    exact = bool(best and published and best in published.replace("+", " ").split())
    return {**row, "verdict": PASS if inside else FAIL, "exact": exact}


def _class_check(row: dict, published: str | None, parts: list[tuple[float, float]] | None) -> dict:
    """Class-level verdict when the tool says "not a brown dwarf" and gives no type range.

    Agreement with a published star or giant is a pass. Disagreement with a published L, T or
    Y type (an L0 or later component, no star or giant wording) is a fail. Anything else
    (no published type, or a late-M type that could be either) is not applicable.
    """
    if published and _STELLAR.search(published):
        return {**row, "verdict": PASS,
                "reason": f"Class only: we say it is not a brown dwarf and the published "
                          f"nature ({published}) is not a brown dwarf either."}
    if parts and all(lo >= 0 for lo, _ in parts):
        return {**row, "verdict": FAIL,
                "reason": f"We say it is not a brown dwarf, but the published type "
                          f"({published}) is a brown dwarf."}
    return {**row, "verdict": NOT_APPLICABLE,
            "reason": "We say it is not a brown dwarf; there is no published type to compare with."
            if not published else "We say it is not a brown dwarf; the published type is not clear-cut."}
