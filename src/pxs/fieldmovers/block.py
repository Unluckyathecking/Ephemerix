"""Pick the tracks that moved, check them between the two WISE bands, count the null and
write the manifest's `field_movers` block (docs/api.md). Thresholds and where they come from
are in the package docstring. Written with Claude Code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pxs import centroid
from pxs.astrometry import px_to_sky
from pxs.fieldmovers import detect, label
from pxs.fieldmovers.detect import Epochs
from pxs.fieldmovers.link import MIN_DETECTIONS, Track, tracks
from pxs.grid import Grid, Stack
from pxs.target import Target

METHOD = "wise_visit_tracks"
BANDS = ("W2", "W1")
SIG_MIN = 6.0
MIN_SHIFT_ARCSEC = 1.0
COVER_MIN = 0.7
BRIGHT_RATIO = 40.0  # 4 mag, as trackmotion.BRIGHT_MAG
BRIGHT_SEP_ARCSEC = 12.0  # trackmotion.BRIGHT_SEP_ARCSEC
NULL_TRIALS = 10
NULL_SEED = 2026
# Unexplained candidates are counted but not listed. The rule set before the search was
# written: list them only if the false-alarm rate is clearly below the rate at which the real
# search turns up unexplained candidates. In the 17 gallery fields the real search turned up
# none (of about 700 tracks that are not the target), and the shuffled null gives 0.007 a field, so
# that cannot be shown. True lists them; `candidates_withheld` in the block says which.
SHIP_CANDIDATES = False
KNOWN = (label.GAIA, label.CATWISE)
WITHHELD = ("{n} possible mover{s} that no catalogue explains {verb} not listed, because this "
            "search cannot yet tell such movers from false alarms.")


@dataclass(frozen=True)
class Band:
    """One band's visits and every track linked in them."""

    ep: Epochs
    tracks: tuple[Track, ...]


@dataclass(frozen=True)
class Mover:
    """A track that moved, with the track of the same source in the other band if any."""

    band: Band
    track: Track
    partner: tuple[Band, Track] | None = None


def shift_arcsec(tr: Track, ep: Epochs) -> float:
    """How far the track moved over the visits searched, in arcsec."""
    return math.hypot(tr.vx, tr.vy) * float(np.ptp(ep.years)) * ep.pixscale_arcsec


def _in_wings(tr: Track, band: Band) -> bool:
    """True when a source BRIGHT_RATIO times brighter comes within BRIGHT_SEP_ARCSEC."""
    years = band.ep.years[list(tr.epochs)]
    for other in band.tracks:
        if other is tr or other.snr < BRIGHT_RATIO * tr.snr:
            continue
        d = np.hypot(tr.x0 + tr.vx * (years - tr.t0) - other.x0 - other.vx * (years - other.t0),
                     tr.y0 + tr.vy * (years - tr.t0) - other.y0 - other.vy * (years - other.t0))
        if float(d.min()) * band.ep.pixscale_arcsec <= BRIGHT_SEP_ARCSEC:
            return True
    return False


def coverage(tr: Track, ep: Epochs) -> float:
    """Share of the visits in which the track is inside the searched area that it was seen in."""
    edge = detect.EDGE_FWHM * centroid.WISE_FWHM_ARCSEC[ep.band] / ep.pixscale_arcsec
    x, y = tr.x0 + tr.vx * (ep.years - tr.t0), tr.y0 + tr.vy * (ep.years - tr.t0)
    inside = (x >= edge) & (x <= ep.size_px - edge) & (y >= edge) & (y <= ep.size_px - edge)
    return len(tr.epochs) / max(int(inside.sum()), len(tr.epochs))


def moved(tr: Track, band: Band) -> bool:
    return (tr.significance >= SIG_MIN and shift_arcsec(tr, band.ep) >= MIN_SHIFT_ARCSEC
            and coverage(tr, band.ep) >= COVER_MIN and not _in_wings(tr, band))


def _partner(tr: Track, other: Band) -> Track | None:
    """The track of the other band at the same place at this track's mean epoch."""
    best, best_d = None, label.MATCH_ARCSEC / other.ep.pixscale_arcsec
    for o in other.tracks:
        ox, oy = o.at(tr.t0)
        d = math.hypot(ox - tr.x0, oy - tr.y0)
        if d <= best_d:
            best, best_d = o, d
    return best


def _consistent(a: Track, b: Track) -> bool:
    diff = math.hypot(a.vx - b.vx, a.vy - b.vy)
    return diff <= max(label.AGREE_SIGMA * math.hypot(a.err_v, b.err_v),
                       label.AGREE_FRACTION * math.hypot(a.vx, a.vy))


def movers(bands: Sequence[Band]) -> tuple[list[Mover], int]:
    """(movers, number dropped because the two bands disagree). A mover seen in both bands
    is listed once, from the band given first in which it moved."""
    out: list[Mover] = []
    taken: set[int] = set()
    conflicts = 0
    for band in bands:
        others = [b for b in bands if b is not band]
        for tr in band.tracks:
            if id(tr) in taken or not moved(tr, band):
                continue
            pair = next(((o, p) for o in others if (p := _partner(tr, o)) is not None), None)
            if pair is not None and not _consistent(tr, pair[1]):
                conflicts += 1
                continue
            if pair is not None:
                taken.add(id(pair[1]))
            out.append(Mover(band, tr, pair))
    return out, conflicts


def band_of(stacks: Sequence[tuple[str, Stack]], ids: Sequence[str], grid: Grid,
            name: str) -> Band | None:
    """The tracks of one band; None with fewer than MIN_DETECTIONS visits."""
    ep = detect.epochs(stacks, ids, grid, name)
    if len(ep.years) < MIN_DETECTIONS:
        return None
    return Band(ep, tuple(tracks(ep)))


def null_counts(bands: Sequence[Band], trials: int = NULL_TRIALS) -> list[int]:
    """Movers found by the same search with the visit dates dealt out at random, per trial
    (the same shuffle in both bands)."""
    counts = []
    for k in range(trials):
        fake = []
        for b in bands:
            ep = detect.scrambled(b.ep, np.random.default_rng(NULL_SEED + k))
            fake.append(Band(ep, tuple(tracks(ep))))
        counts.append(len(movers(fake)[0]))
    return counts


def _clip(xy: tuple[float, float], size: int) -> list[float]:
    return [round(min(max(float(v), 0.0), float(size)), 2) for v in xy]


def entry(m: Mover, target: Target, grid: Grid, gaia: Sequence[dict],
          catwise: Sequence[dict]) -> dict:
    """One `movers` entry of the block."""
    tr, ep = m.track, m.band.ep
    pmra, pmdec, err = label.motion_masyr(tr, grid.pixscale_arcsec)
    ra, dec = px_to_sky(tr.x0, tr.y0, grid.center_ra, grid.center_dec, grid.fov_arcsec,
                        grid.size_px)
    seen = [ep.ids[k] for k in tr.epochs]
    if m.partner is not None:
        seen += [m.partner[0].ep.ids[k] for k in m.partner[1].epochs]
    years = ep.years[list(tr.epochs)]
    return {
        **label.label(tr, target, grid, gaia, catwise),
        "bands": [ep.band, *([m.partner[0].ep.band] if m.partner else [])],
        "epoch": round(tr.t0, 3), "px": _clip((tr.x0, tr.y0), grid.size_px),
        "ra": round(float(ra), 6), "dec": round(float(dec), 6),
        "first_px": _clip(tr.at(float(years[0])), grid.size_px),
        "last_px": _clip(tr.at(float(years[-1])), grid.size_px),
        "first_year": round(float(years[0]), 2), "last_year": round(float(years[-1]), 2),
        "pmra_masyr": round(pmra, 1), "pmdec_masyr": round(pmdec, 1), "err_masyr": round(err, 1),
        "motion_arcsec_yr": round(math.hypot(pmra, pmdec) / 1000.0, 3),
        "shift_arcsec": round(shift_arcsec(tr, ep), 2),
        "significance": round(tr.significance, 1), "snr": round(tr.snr, 1),
        "n_epochs": len(tr.epochs), "epochs": seen,
    }


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def sentence(years: tuple[int, int], entries: Sequence[dict], n_candidates: int,
             withheld: bool) -> str:
    """The line a visitor reads."""
    known = [e for e in entries if e["label"] in KNOWN]
    noun = "star" if all(e["label"] == label.GAIA for e in known) else "object"
    found = [f"{_count(len(known), noun)} already known to move"] if known else []
    if not n_candidates:
        found.append("nothing unexplained")
    elif not withheld:
        found.append(_count(n_candidates, "unexplained candidate"))
    text = f"We searched this patch for anything else that moved between {years[0]} and {years[1]}."
    text += (f" We found {' and '.join(found)}." if found
             else " We found no catalogued star that moved enough to measure.")
    if any(e["label"] == label.TARGET for e in entries):
        text += " The search also picked up the target itself without being told where it is."
    if withheld and n_candidates:
        text += " " + WITHHELD.format(n=n_candidates, s="" if n_candidates == 1 else "s",
                                      verb="is" if n_candidates == 1 else "are")
    return text


def not_searched(reason: str) -> dict:
    return {"status": "not_searched", "reason": reason, "method": METHOD, "movers": [],
            "sentence": f"We did not search this patch for other moving objects, because {reason}."}


def assemble(bands: Sequence[Band], target: Target, grid: Grid, gaia: Sequence[dict],
             catwise: Sequence[dict], ship_candidates: bool | None = None) -> dict:
    """The `field_movers` block of a searched field (`ship_candidates` None: SHIP_CANDIDATES)."""
    ship_candidates = SHIP_CANDIDATES if ship_candidates is None else ship_candidates
    found, conflicts = movers(bands)
    entries = sorted((entry(m, target, grid, gaia, catwise) for m in found),
                     key=lambda e: -e["significance"])
    shown = [e for e in entries if e["label"] != label.CONTRADICTED
             and (ship_candidates or e["label"] != label.CANDIDATE)]
    n_cand = sum(e["label"] == label.CANDIDATE for e in entries)
    null = null_counts(bands)
    years = np.concatenate([b.ep.years for b in bands])
    span = (int(years.min()), int(years.max()))
    return {
        "status": "searched", "reason": None, "method": METHOD,
        "bands": [b.ep.band for b in bands],
        "first_year": round(float(years.min()), 2), "last_year": round(float(years.max()), 2),
        "baseline_years": round(float(np.ptp(years)), 2),
        "n_epochs": {b.ep.band: len(b.ep.years) for b in bands},
        "n_tracked": {b.ep.band: len(b.tracks) for b in bands},
        "limits": {"snr_min": detect.SNR_MIN, "significance_min": SIG_MIN,
                   "shift_min_arcsec": MIN_SHIFT_ARCSEC, "min_epochs": MIN_DETECTIONS},
        "movers": shown,
        "n_known": sum(e["label"] in KNOWN for e in entries),
        "n_candidates": n_cand, "candidates_withheld": not ship_candidates,
        "n_contradicted": sum(e["label"] == label.CONTRADICTED for e in entries),
        "n_band_conflicts": conflicts,
        "null_count": round(float(np.mean(null)), 2), "null_max": int(max(null)),
        "null_trials": len(null),
        "sentence": sentence(span, shown, n_cand, not ship_candidates),
    }
