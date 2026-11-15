"""Hard fields: glare that hides the object, a crowded field, and a motion too thin to mean
anything. Pure functions over frame entries and the manifest. Written with Claude Code.

Per frame (`frame_gaps`): `no_data_fraction`, the share of the frame with no usable measurement
(`render.no_data_mask`: no coverage, or flagged in most exposures), and `no_data_near_target`,
that share within GLARE_RADIUS_ARCSEC of where the target should be.

Glare (`field.saturated`): in the median WISE frame, at least GLARE_WISE_SHARE of the disc
around the target has no data, so the glare covers it, not just a saturated core. The median
WISE and SPHEREx shares, rebuilt today: Betelgeuse 1.0 and 1.0, Sagittarius A* 1.0 and 0.55,
R Draconis 0.48 and 0.81, Barnard's Star 0.12 and 0.28, RW Aurigae 0.04 and 0.01. WISE decides,
because a star that only saturates SPHEREx (R Draconis, Barnard's Star: no usable spectrum)
still shows as a star with a core in WISE. `saturated_missions` names WISE and, when its median
share is at least GLARE_SHARE, SPHEREx too.

A view with no WISE frame at all (the WISE images could not be loaded) has only SPHEREx to
judge by: glare is then called when the median share is at least GLARE_SHARE in more than
half of the SPHEREx bands shown (Betelgeuse: 1.0 in all six), `saturated_missions` is
["SPHEREx"], and the sentence names SPHEREx alone.

Crowding (`field.crowded`): the catalogue lists are the brightest MAX_SOURCES sources around
the field, so a full CatWISE list whose faintest source is brighter than W2 CROWDED_FAINTEST_W2
means more than that many sources brighter than W2 15 nearby, several per WISE beam. Every
gallery field's list reaches W2 16.3 or fainter. Null when CatWISE did not answer: the counts
we tried from the images (peaks, bright-pixel share) did not separate the Galactic centre from
the gallery's fields near the Milky Way, so they are not used.

Motion (`gate_motion`): a motion from fewer than MIN_DETECTIONS detections, or over less than
MIN_BASELINE_YEARS, is not reported: one year of positions cannot tell motion from parallax.
When the WISE images could not be loaded that is the reason given: SPHEREx alone spans under
two years, so no motion can be published without them.
The 16 measured gallery motions have at least 5 detections over at least 9.99 years.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from pxs import render, trackmotion
from pxs.grid import Stack

GLARE_RADIUS_ARCSEC = 30.0
GLARE_WISE_SHARE = 0.8
GLARE_SHARE = 0.5
GLARE_FLAG_FRACTION = 0.5  # a frame with this share of its pixels flagged gives no detection
CROWDED_FAINTEST_W2 = 15.0
CROWDED_MIN_SOURCES = 100  # a full list, inside the field (64% of the capped circle)
MIN_DETECTIONS = 4
MIN_BASELINE_YEARS = 3.0
MISSION_WORDS = {("WISE",): "WISE", ("SPHEREx", "WISE"): "both WISE and SPHEREx",
                 ("SPHEREx",): "SPHEREx"}
NO_WISE_REASON = ("the WISE images could not be loaded; a motion needs their years of "
                  "positions")


def frame_gaps(stack: Stack, at_px: tuple[float, float], pixscale_arcsec: float) -> dict:
    """`no_data_fraction` and `no_data_near_target` for one frame (the latter null when the
    target position is off the frame)."""
    mask = render.no_data_mask(stack)
    ny, nx = mask.shape
    near = None
    if 0.0 <= at_px[0] <= nx and 0.0 <= at_px[1] <= ny:
        i, j = np.mgrid[:ny, :nx]
        disc = np.hypot(j + 0.5 - at_px[0], i + 0.5 - at_px[1]) * pixscale_arcsec \
            <= GLARE_RADIUS_ARCSEC
        near = round(float(mask[disc].mean()), 4)
    return {"no_data_fraction": round(float(mask.mean()), 4), "no_data_near_target": near}


def glare(frames: Sequence[dict]) -> dict[str, float]:
    """Median `no_data_near_target` per mission, over frames that have it."""
    out: dict[str, list[float]] = {}
    for f in frames:
        if f.get("no_data_near_target") is not None:
            out.setdefault(f["mission"], []).append(f["no_data_near_target"])
    return {m: round(float(np.median(v)), 3) for m, v in sorted(out.items())}


def crowding(catwise: Sequence[dict] | None) -> dict | None:
    """{"crowded", "catwise_sources", "faintest_w2"}, or None when CatWISE did not answer."""
    if catwise is None:
        return None
    mags = [s["w2_mag"] for s in catwise if s.get("w2_mag") is not None]
    faintest = max(mags) if mags else None
    crowded = (len(catwise) >= CROWDED_MIN_SOURCES and faintest is not None
               and faintest < CROWDED_FAINTEST_W2)
    return {"crowded": bool(crowded), "catwise_sources": len(catwise),
            "faintest_w2": None if faintest is None else round(float(faintest), 2)}


def spherex_glare(frames: Sequence[dict]) -> bool:
    """True when the median `no_data_near_target` is at least GLARE_SHARE in more than half
    of the SPHEREx bands that have frames."""
    bands: dict[str, list[float]] = {}
    for f in frames:
        if f["mission"] == "SPHEREx" and f.get("no_data_near_target") is not None:
            bands.setdefault(f.get("band"), []).append(f["no_data_near_target"])
    glared = sum(float(np.median(v)) >= GLARE_SHARE for v in bands.values())
    return 2 * glared > len(bands)


def field(frames: Sequence[dict], catwise: Sequence[dict] | None) -> dict:
    """The manifest's `field` block (docs/api.md)."""
    near = glare(frames)
    if any(f["mission"] == "WISE" for f in frames):
        glared = near.get("WISE", 0.0) >= GLARE_WISE_SHARE
        sat = sorted(m for m, v in near.items() if v >= GLARE_SHARE) if glared else []
    else:  # no WISE frame to judge by
        sat = ["SPHEREx"] if spherex_glare(frames) else []
    crowd = crowding(catwise)
    return {"saturated": bool(sat), "saturated_missions": sat, "no_data_near_target": near,
            "crowded": None if crowd is None else crowd["crowded"], "crowding": crowd}


def sentences(f: dict) -> list[str]:
    """The plain sentences for the top of `warnings`, glare first."""
    out = []
    if f["saturated"]:
        who = MISSION_WORDS[tuple(f["saturated_missions"])]
        out.append(f"This spot is so bright in the infrared that it overloads {who}: most of "
                   "the images show glare and detector artefacts rather than the object itself, "
                   "and the flat patches in them are where there is no usable measurement.")
    if f["crowded"]:
        out.append("This field is too crowded to follow one object: there are more than 200 "
                   "catalogued sources brighter than W2 15 around it, so neighbours blend "
                   "together in these images.")
    return out


def gate_motion(motion: dict | None, f: dict, frames: Sequence[dict] = (),
                wise_missing: bool = False) -> tuple[dict | None, dict | None]:
    """(measured_motion to publish, motion_not_measured). A motion is not measured when it
    rests on fewer than MIN_DETECTIONS positions, spans less than MIN_BASELINE_YEARS, or is an
    all-frames fit in glare; with no motion at all, only when some frame has a detection (all
    of them then in frames left out as mostly glare or gaps). With `wise_missing` (the WISE
    images could not be loaded) a missing or thin motion is put down to that."""
    if wise_missing and (motion is None or (motion.get("baseline_years") or 0.0)
                         < MIN_BASELINE_YEARS):
        return None, {"reason": NO_WISE_REASON,
                      "n_detections": (motion or {}).get("n_detections", 0),
                      "baseline_years": (motion or {}).get("baseline_years") or 0.0}
    if motion is None:
        det = [fr for fr in frames if fr.get("centroid_px") is not None]
        if not det or any(fr.get("flag_fraction", 0.0) < GLARE_FLAG_FRACTION for fr in det):
            return None, None
        return None, {"reason": "every detection is in an image that is mostly glare or gaps",
                      "n_detections": 0, "baseline_years": 0.0}
    n = motion.get("n_frames") if motion.get("method") == "all_frames" else motion.get("n_detections")
    base = motion.get("baseline_years") or 0.0
    reason = None
    if motion.get("method") == "all_frames" and f["saturated"]:
        reason = "the images near the object are glare, so a fit to all of them means nothing"
    elif (n or 0) < MIN_DETECTIONS or base < MIN_BASELINE_YEARS:
        reason = (f"only {n} clean detection{'' if n == 1 else 's'} over {base:g} year"
                  f"{'' if base == 1 else 's'}; we need at least {MIN_DETECTIONS} over "
                  f"{MIN_BASELINE_YEARS:g} years to tell motion from parallax and noise")
    if reason is None:
        return motion, None
    return None, {"reason": reason, "n_detections": n, "baseline_years": base}


def not_measured_sentence(nm: dict) -> str:
    return f"Motion not measured: {nm['reason']}."


def apply(manifest: dict, catwise: Sequence[dict] | None, wise_failed: bool = False) -> dict:
    """The manifest with `field`, the gated `measured_motion`, `motion_not_measured`, and the
    field and motion sentences at the top of `warnings`. `wise_failed`: the WISE search or
    stacking failed (as opposed to: WISE has no frames here)."""
    f = field(manifest["frames"], catwise)
    no_wise = wise_failed and not any(fr["mission"] == "WISE" for fr in manifest["frames"])
    motion, nm = gate_motion(manifest.get("measured_motion"), f, manifest["frames"], no_wise)
    top = sentences(f) + ([not_measured_sentence(nm)] if nm else [])
    stale = trackmotion.NOTE.split("{")[0] if nm else None  # the all-frames note, now refused
    rest = [w for w in manifest["warnings"]
            if w not in top and not (stale and w.startswith(stale))]
    return {**manifest, "field": f, "measured_motion": motion, "motion_not_measured": nm,
            "warnings": top + rest}
