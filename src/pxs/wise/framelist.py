"""Committed WISE frame lists: frame discovery for known positions with no IRSA query.

IRSA's search services (SIA, TAP, IBE) can be down for days while the frames themselves stay
readable in s3://nasa-irsa-wise. ``tools/wise_frames/build_lists.py`` writes one JSON file per gallery
target into ``data/frames/wise/`` (override with ``PXS_WISE_FRAMES``) while a search works,
and ``lookup`` serves those frames for any search circle that one file's circle contains.

A file records, per mission phase, how its frames were listed ("complete"), why the phase
has none here ("none"), or that it could not be listed ("missing"); a missing phase makes the
result ``partial`` with the same sentence a failed live search gives. ``lookup`` never
raises: on any problem it returns None and the caller searches IRSA as before.

File layout (version 1)::

    {"version": 1, "ra": deg, "dec": deg, "radius_deg": deg, "made": "YYYY-MM-DD",
     "phases": {"allsky": {"status": "complete", "how": "..."}, ...},
     "frames": [[phase, scan_id, frame_num, band, mjd, qual_frame|null, saa_sep|null,
                 [ra1, dec1, ..., ra4, dec4]], ...]}
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

from pxs.wise.frames import Frame
from pxs.wise.phases import PHASES

log = logging.getLogger(__name__)

ENV_DIR = "PXS_WISE_FRAMES"
DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "frames" / "wise"
VERSION = 1
STATUSES = ("complete", "none", "missing")
_EPS_DEG = 1e-6
PHASE_YEARS = {"allsky": "2010 (cryogenic)", "3band": "2010 (three-band)",
               "postcryo": "2010-2011 (post-cryogenic)", "neowiser": "2013-2024 (NEOWISE)"}

Listed = tuple[list[Frame], list[str]]  # frames sorted by time, phases not listed


def frames_dir() -> Path:
    return Path(os.environ.get(ENV_DIR) or DEFAULT_DIR)


def _sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    c = (math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def covers(doc: dict, ra: float, dec: float, radius_deg: float) -> bool:
    """True when the file's circle contains the search circle."""
    sep = _sep_deg(doc["ra"], doc["dec"], ra, dec)
    return sep + radius_deg <= doc["radius_deg"] + _EPS_DEG


def to_frame(row: list) -> Frame:
    phase, scan_id, frame_num, band, mjd, qual, saa, c = row
    corners = tuple((float(c[i]), float(c[i + 1])) for i in range(0, len(c), 2))
    return Frame(phase=phase, scan_id=scan_id, frame_num=int(frame_num), band=band,
                 mjd=float(mjd), corners=corners,
                 qual_frame=None if qual is None else int(qual),
                 saa_sep_deg=None if saa is None else float(saa))


def to_row(f: Frame, digits: int = 6) -> list:
    """A Frame as a compact JSON row (corners rounded to ``digits`` decimals of a degree)."""
    c = [round(v, digits) for pt in f.corners for v in pt]
    saa = None if f.saa_sep_deg is None else round(f.saa_sep_deg, 3)
    return [f.phase, f.scan_id, f.frame_num, f.band, round(f.mjd, 8), f.qual_frame, saa, c]


def missing_warning(phases: list[str]) -> str:
    years = ", ".join(PHASE_YEARS[p] for p in phases)
    return (f"The IRSA search for WISE frames from {years} failed, so those frames are "
            "missing.")


def no_quality_warning(phases: list[str]) -> str:
    years = ", ".join(PHASE_YEARS[p] for p in phases)
    return (f"Catalogue frame-quality scores were unavailable for the WISE frames from {years}, "
            "so those frames were checked by their measured pixel noise instead.")


def _check(doc: dict) -> None:
    if doc.get("version") != VERSION:
        raise ValueError(f"unsupported frame-list version {doc.get('version')!r}")
    phases = doc["phases"]
    if set(phases) != {p.name for p in PHASES}:
        raise ValueError("frame list must state every phase")
    if any(v["status"] not in STATUSES for v in phases.values()):
        raise ValueError("unknown phase status")


def load(path: Path) -> dict:
    doc = json.loads(path.read_text())
    _check(doc)
    return doc


def result(doc: dict) -> Listed:
    """(frames sorted by time, names of the phases that could not be listed)."""
    frames = sorted((to_frame(r) for r in doc["frames"]), key=lambda f: (f.mjd, f.key))
    missing = [p.name for p in PHASES if doc["phases"][p.name]["status"] == "missing"]
    return frames, missing


def warnings(frames: list[Frame], missing: list[str]) -> tuple[str, ...]:
    """Sentences for the user: phases whose frames have no score, then phases not listed."""
    no_qual = [p.name for p in PHASES
               if any(f.phase == p.name and f.qual_frame is None for f in frames)]
    out = []
    if no_qual:
        out.append(no_quality_warning(no_qual))
    if missing:
        out.append(missing_warning(missing))
    return tuple(out)


def lookup(ra: float, dec: float, radius_deg: float) -> Listed | None:
    """(frames, missing phases) from the first committed list containing the circle, or
    None when no list does or anything goes wrong (the caller then searches IRSA)."""
    try:
        root = frames_dir()
        if not root.is_dir():
            return None
        for path in sorted(root.glob("*.json")):
            doc = load(path)
            if covers(doc, ra, dec, radius_deg):
                log.info("WISE frames for %.5f %.5f r=%.4f from %s", ra, dec, radius_deg,
                         path.name)
                return result(doc)
    except Exception as exc:  # noqa: BLE001 - a bad list must never break a build
        log.warning("WISE frame lists unusable (%s: %s); searching IRSA",
                    type(exc).__name__, exc)
    return None
