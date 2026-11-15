"""Drop centroids in a secondary band that disagree with the same epoch's reference band.

One visit (WISE) or pass (SPHEREx) sees the same object in every band, so its position minus
the predicted position must agree between bands. A W1 "detection" 3 arcsec from the W2 one
at the same visit (WISE 0855 in 2010, where the brown dwarf is invisible in W1 and a static
source sits nearby) is another object. Reference bands are W2 and spx-b6; a secondary-band
centroid whose residual differs from the reference's by more than TOLERANCE_SIGMA combined
errors is replaced by "not detected" with a note. Frames without a detected reference are
left alone. Pixels in grid units, errors in arcsec.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

REFERENCE = {"WISE": "W2", "SPHEREx": "spx-b6"}
SAME_EPOCH_DAYS = {"WISE": 5.0, "SPHEREx": 30.0}
TOLERANCE_SIGMA = 3.0
DISAGREES = "position disagrees with {ref} at the same epoch, so it is not counted as the target"


def _residual(f: dict) -> tuple[float, float] | None:
    if f["centroid_px"] is None or f["predicted_px"] is None:
        return None
    return (f["centroid_px"][0] - f["predicted_px"][0], f["centroid_px"][1] - f["predicted_px"][1])


def _reference(f: dict, frames: Sequence[dict]) -> dict | None:
    ref_band = REFERENCE.get(f["mission"])
    window = SAME_EPOCH_DAYS.get(f["mission"], 0.0)
    near = [g for g in frames if g["band"] == ref_band and abs(g["mjd"] - f["mjd"]) <= window
            and _residual(g) is not None]
    return min(near, key=lambda g: abs(g["mjd"] - f["mjd"]), default=None)


def _disagrees(f: dict, ref: dict, arcsec_per_px: float) -> bool:
    a, b = _residual(f), _residual(ref)
    sep = math.hypot(a[0] - b[0], a[1] - b[1]) * arcsec_per_px
    tol = TOLERANCE_SIGMA * math.hypot(f["centroid_err_arcsec"], ref["centroid_err_arcsec"])
    return sep > tol


def check(frames: Sequence[dict], arcsec_per_px: float) -> list[dict]:
    """New frame entries with disagreeing secondary-band centroids set to not detected."""
    out = []
    for f in frames:
        ref = None if f["band"] == REFERENCE.get(f["mission"]) else _reference(f, frames)
        if ref is None or _residual(f) is None or not _disagrees(f, ref, arcsec_per_px):
            out.append(f)
            continue
        note = DISAGREES.format(ref=ref["band"])
        out.append({**f, "centroid_px": None, "centroid_err_arcsec": None,
                    "warnings": [*f["warnings"], note]})
    return out
