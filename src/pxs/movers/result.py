"""Result types of a field search and their JSON form.

Every candidate that is not a catalogued body is labelled "unvetted candidate" with its
false-alarm probability; the search never claims a discovery.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LABEL_KNOWN = "known object"
LABEL_STAR = "coincides with a catalogued star"
LABEL_INCONSISTENT = "fails half-pass consistency"
LABEL_UNVETTED = "unvetted candidate"


@dataclass(frozen=True)
class Candidate:
    """A track above threshold. ra, dec: degrees at mjd_mid. rate in arcsec/hour, position
    angle in degrees east of north. distance_au: range of distances whose allowed rates
    contain the track (broad by nature). vet_score: advisory P(real mover) from the vetting
    model (SearchResult.vet), None without a model; it never changes the label. flux_ujy: at 1 um for a solar-coloured body.
    band_frames: frames on the track per detector ("D1": n). fap: probability that the
    mirrored null search gives a peak this bright in this field-pass."""

    rank: int
    label: str
    ra: float
    dec: float
    mjd_mid: float
    rate_arcsec_h: float
    pa_deg: float
    distance_au: tuple[float, float]
    snr: float
    snr_unclipped: float
    snr_first_half: float
    snr_second_half: float
    flux_ujy: float
    flux_err_ujy: float
    band_frames: dict[str, int]
    fap: float
    known_name: str | None = None
    known_vmag: float | None = None
    stamps: dict[str, Any] = field(default_factory=dict)
    vet_score: float | None = None


@dataclass(frozen=True)
class Limit:
    """Completeness of the field-pass from injections (reflected-light template)."""

    flux_ujy: list[float]
    completeness: list[float]
    n_injected: list[int]
    flux50_ujy: float
    flux90_ujy: float
    vmag50: float
    vmag90: float
    statement: str
    distance_curves: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResult:
    """Everything about one field-pass search."""

    center_ra: float
    center_dec: float
    size_arcmin: float
    pass_mjd: tuple[float, float]
    n_frames: int
    n_reference_frames: int
    n_reference_passes: int
    masked_fraction: float
    n_trials: int
    threshold: float
    min_motion_px: float
    candidates: list[Candidate]
    null_peaks_above_threshold: int
    null_max_snr: float
    timings_s: dict[str, float]
    limit: Limit | None = None
    warnings: list[str] = field(default_factory=list)
    vet: dict[str, Any] | None = None
    claim: str = ("Recovers known distant bodies and measures its own detection limits. "
                  "Unvetted candidates are not discoveries.")

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return _clean(d)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))


def _clean(v: Any) -> Any:
    """NaN and inf become null so the file is strict JSON; tuples become lists."""
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, 6)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v
