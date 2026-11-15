"""Facts read straight off a manifest: frame counts, epochs, degraded reasons, residuals."""

import math
import re

_DEGRADED = re.compile(r"did not arrive|failed|could not be fetched|are missing|is missing", re.IGNORECASE)
_GAP = re.compile(r"search for WISE frames from .* failed", re.IGNORECASE)
_DECLINED = re.compile(r"not classified|no spectrum to judge|unusable|too little of the spectrum to classify", re.IGNORECASE)


def epoch_key(frame_id: str) -> str:
    """'wise-w1-2010a' and 'spx-b2-2010a' share the visit key '2010a'."""
    return frame_id.rsplit("-", 1)[-1]


def degraded_info(manifest: dict) -> dict:
    """Whether the build was degraded, and the manifest's own warnings that say why."""
    warnings = [w for w in manifest.get("warnings", []) if isinstance(w, str)]
    return {"flag": bool(manifest.get("degraded")),
            "reasons": [w for w in warnings if _DEGRADED.search(w)]}


def declined_reason(manifest: dict) -> str | None:
    """The manifest warning that says why the spectrum was not classified, if any."""
    for w in manifest.get("warnings", []):
        if isinstance(w, str) and _DECLINED.search(w):
            return w
    return None


def frame_stats(manifest: dict) -> dict:
    """Frames and epochs per mission, WISE year span, and missing-coverage warnings."""
    frames = manifest.get("frames", [])
    wise = [f for f in frames if f.get("mission") == "WISE"]
    spx = [f for f in frames if f.get("mission") == "SPHEREx"]
    years = sorted({int(f["date"][:4]) for f in wise if f.get("date")})
    warnings = [w for w in manifest.get("warnings", []) if isinstance(w, str)]
    return {
        "wise": {"frames": len(wise), "epochs": len({epoch_key(f["id"]) for f in wise}),
                 "first_year": years[0] if years else None,
                 "last_year": years[-1] if years else None},
        "spherex": {"frames": len(spx), "epochs": len({epoch_key(f["id"]) for f in spx})},
        "gaps": [w for w in warnings if _GAP.search(w)],
    }


def residual_info(manifest: dict) -> dict:
    """Largest distance of a measured centroid from the predicted track, with its frame.

    Manifest pixels are display pixels; arcsec per pixel is fov_arcsec / size_px.
    """
    scale = manifest["fov_arcsec"] / manifest["size_px"]
    frames = manifest.get("frames", [])
    best: tuple[float, dict] | None = None
    measured = 0
    for f in frames:
        c, p = f.get("centroid_px"), f.get("predicted_px")
        if not c or not p:
            continue
        measured += 1
        d = math.hypot(c[0] - p[0], c[1] - p[1])
        if best is None or d > best[0]:
            best = (d, f)
    base = {"frames": len(frames), "measured": measured, "undetected": len(frames) - measured}
    if best is None:
        return {**base, "max_px": None}
    d, f = best
    native = f.get("native_pixscale_arcsec")
    return {**base, "max_px": d, "max_arcsec": d * scale, "frame_id": f["id"],
            "mission": f.get("mission"), "native_pixscale_arcsec": native,
            "max_native_px": d * scale / native if native else None,
            "frame_warnings": list(f.get("warnings", []))}


def motion_missing_reason(manifest: dict) -> str:
    """Why `measured_motion` is empty, from the manifest's own warnings and frame counts."""
    for w in manifest.get("warnings", []):
        if isinstance(w, str) and "not detected in any frame" in w:
            return "The target was not detected in any frame, so no motion was measured."
    for w in manifest.get("warnings", []):
        if isinstance(w, str) and "motion fit" in w:  # the view's own account, e.g. blended detections left out
            return w
    n = sum(1 for f in manifest.get("frames", []) if f.get("centroid_px"))
    return (f"Only {n} detection{'' if n == 1 else 's'}, fewer than the two needed, so no motion "
            "was measured." if n < 2 else "No motion was measured for this view, and it gives no reason.")
