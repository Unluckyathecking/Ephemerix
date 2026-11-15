"""Targets, the interfaces of the WISE and SPHEREx data modules, and the loops that call them.

Units: angles in degrees (ICRS), proper motion in mas/yr (pmra includes cos dec),
epochs as decimal years, wavelengths in micrometres, fluxes in mJy.

`pxs.build` depends only on the two Protocols here. The real modules
(`pxs.wise`, `pxs.spherex`) are passed in, so tests use fakes.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pxs.concurrency import map_ordered
from pxs.grid import Grid, Stack
from pxs.target import Target, TargetError, load_targets, slugify, target_from_dict

log = logging.getLogger(__name__)

__all__ = ["Target", "TargetError", "load_targets", "slugify", "target_from_dict"]

# Frame-set ids (docs/api.md) and their stacking windows in micrometres. One SPHEREx window
# per detector array (D1-D6 ranges measured on real frames: 0.75-1.10, 1.09-1.65,
# 1.62-2.42, 2.41-3.79, 3.81-4.42, 4.41-5.01 um), so each set co-adds one array.
WISE_BANDS: tuple[str, ...] = ("W2", "W1")
WISE_PARALLEL = 12  # WISE (visit, band) stacks built at once; each reads up to 16 frames
PASS_PARALLEL = 4  # SPHEREx passes processed at once
SPHEREX_WINDOWS: dict[str, tuple[float, float]] = {
    "spx-b1": (0.75, 1.10),
    "spx-b2": (1.10, 1.65),
    "spx-b3": (1.65, 2.42),
    "spx-b4": (2.42, 3.82),
    "spx-b5": (3.82, 4.42),
    "spx-b6": (4.42, 5.00),
}


Sky = tuple[float, float]  # (ra, dec) degrees
# Catalogued sources other than the target at a pass's epoch, or None when unknown.
Neighbours = Callable[[Any], Sequence[Sky] | None]


class SpecPoint(Protocol):
    """One forced-photometry point from `pxs.spherex.extract_spectrum`."""

    wl_um: float
    bw_um: float
    flux_mjy: float | None
    err_mjy: float | None
    detector: int
    flagged: bool
    mjd: float


class SpherexSource(Protocol):
    """The `pxs.spherex` module."""

    def find_frames(self, ra: float, dec: float) -> list[Any]: ...
    def group_passes(self, frames: list[Any]) -> list[Any]: ...
    def stack_pass(
        self, pas: Any, grid: Grid, window_um: tuple[float, float], target: Any = None
    ) -> Stack | None: ...
    def extract_spectrum(self, pas: Any, target: Any,
                         neighbours: Sequence[Sky] | None = None) -> list[SpecPoint]: ...


class WiseSource(Protocol):
    """The `pxs.wise` module."""

    def find_visits(self, ra: float, dec: float) -> list[Any]: ...
    def stack_visit(self, visit: Any, band: str, grid: Grid) -> Stack | None: ...


@dataclass(frozen=True)
class Collected:
    """What the data modules gave for one view: (frame-set id, Stack) pairs and spectra."""

    stacks: tuple[tuple[str, Stack], ...] = ()
    passes: tuple[tuple[SpecPoint, ...], ...] = ()
    warnings: tuple[str, ...] = ()
    failed: bool = False  # a fetch or stack failed (as opposed to: there were no data)


def _find_visits(wise: WiseSource, target: Target) -> list[Any]:
    """Visits along a mover's path when the module can follow one (frames per visit then
    cover the target where it was at that date), else at the catalogue position."""
    path_from_motion = getattr(wise, "path_from_motion", None)
    if not target.has_pm or path_from_motion is None:
        return wise.find_visits(target.ra, target.dec)
    path = path_from_motion(target.ra, target.dec, target.epoch, target.pmra_masyr,
                            target.pmdec_masyr)
    return wise.find_visits(target.ra, target.dec, path=path)


def collect_wise(wise: WiseSource | None, target: Target, grid: Grid) -> Collected:
    """W2 and W1 stacks for every WISE visit. A failure becomes a warning, never an exception."""
    if wise is None:
        return Collected(warnings=("WISE images are not available in this build.",))
    try:
        visits = _find_visits(wise, target)
    except Exception:
        log.exception("WISE search failed")
        return Collected(warnings=("WISE images could not be loaded; the archive did not answer.",),
                         failed=True)
    def one(job: tuple[Any, str]) -> Stack | None | Exception:
        try:
            return wise.stack_visit(job[0], job[1], grid)
        except Exception as exc:
            log.exception("WISE stack failed for %s", job[1])
            return exc

    jobs = [(visit, band) for visit in visits for band in WISE_BANDS]
    got = map_ordered(one, jobs, WISE_PARALLEL)  # visits read at once; order kept
    stacks = [(b, st) for (_, b), st in zip(jobs, got)
              if st is not None and not isinstance(st, Exception)]
    failed = sum(isinstance(st, Exception) for st in got)
    warnings = (f"{failed} WISE stacks failed and are left out.",) if failed else ()
    warnings += tuple(getattr(visits, "warnings", ()))  # e.g. frame quality unknown
    if not visits:
        warnings += ("No WISE visits were found at this position.",)
    partial = bool(getattr(visits, "partial", False))  # the search could not list every frame
    return Collected(stacks=tuple(stacks), warnings=warnings, failed=failed > 0 or partial)


def _spherex_pass(spherex: SpherexSource, pas: Any, grid: Grid, target: Target,
                  neighbours: Neighbours | None = None):
    """Stacks in the three windows and the spectrum of one pass, plus failure counts."""
    prefetch = getattr(spherex, "prefetch_pass", None)  # read each frame once, for all below
    if prefetch is not None:
        try:
            prefetch(pas, grid, target)
        except Exception:
            log.exception("SPHEREx prefetch failed; the reads below retry")

    def window(item: tuple[str, tuple[float, float]]) -> Stack | None | Exception:
        try:
            return spherex.stack_pass(pas, grid, item[1], target)
        except Exception as exc:
            log.exception("SPHEREx stack failed for %s", item[0])
            return exc

    def spectrum() -> tuple[tuple, int] | Exception:
        try:
            nb = None if neighbours is None else neighbours(pas)
            if nb is None:  # sources without catalogue support keep the two-argument call
                result = spherex.extract_spectrum(pas, target)
            else:
                result = spherex.extract_spectrum(pas, target, neighbours=nb)
            return tuple(result), int(getattr(result, "skipped", 0))
        except Exception as exc:
            log.exception("SPHEREx spectrum failed")
            return exc

    # The windows and the spectrum are independent: all at once (in worker processes when
    # the module offloads them), order kept.
    jobs = [lambda it=it: window(it) for it in SPHEREX_WINDOWS.items()] + [spectrum]
    *wins, spec = map_ordered(lambda job: job(), jobs, len(jobs))
    stacks = [(band, st) for band, st in zip(SPHEREX_WINDOWS, wins)
              if st is not None and not isinstance(st, Exception)]
    failed = sum(isinstance(st, Exception) for st in wins) + isinstance(spec, Exception)
    points, skipped = ((), 0) if isinstance(spec, Exception) else spec
    return stacks, points, failed, skipped


def _find_frames(spherex: SpherexSource, target: Target) -> list[Any]:
    """Frames covering the target's 2025-2027 path when the module can search for a mover."""
    by_target = getattr(spherex, "find_frames_for_target", None)
    if by_target is not None:
        return by_target(target)
    return spherex.find_frames(target.ra, target.dec)


def flag_reasons(passes: Sequence[Sequence[SpecPoint]]) -> list[str]:
    """Plain sentences counting flagged spectrum points by their `reason`, if any."""
    allp = [p for ps in passes for p in ps]
    reasons = Counter(getattr(p, "reason", "") or "flagged" for p in allp if p.flagged)
    if not reasons:
        return []
    n = sum(reasons.values())
    parts = ", ".join(f"{c} {_WHY.get(k, k)}" for k, c in reasons.most_common())
    if n == len(allp):
        return [(f"Every SPHEREx spectrum point is unusable ({parts}), so there is no "
                 "spectrum to judge.")]
    return [f"{n} of {len(allp)} SPHEREx spectrum points are left out ({parts})."]


_WHY = {"saturated": "where the target saturates the detector",
        "masked": "where too much of the target is covered by bad pixels",
        "no psf": "with no PSF model", "no background": "with no clean background",
        "flagged": "flagged"}


def collect_spherex(spherex: SpherexSource | None, target: Target, grid: Grid,
                    neighbours: Neighbours | None = None) -> Collected:
    """Stacks in the three SPHEREx windows and a spectrum for every pass. `neighbours(pas)`
    gives the catalogued sources near the target at that pass, for the recentring."""
    if spherex is None:
        return Collected(warnings=("SPHEREx data are not available in this build.",))
    try:
        passes = spherex.group_passes(_find_frames(spherex, target))
    except Exception:
        log.exception("SPHEREx search failed")
        return Collected(warnings=("SPHEREx data could not be loaded; the archive did not answer.",),
                         failed=True)
    stacks, spectra, failed, skipped = [], [], 0, 0
    per_pass = map_ordered(lambda pas: _spherex_pass(spherex, pas, grid, target, neighbours),
                           passes,
                           PASS_PARALLEL)  # passes at once; order kept
    for s, points, f, k in per_pass:
        stacks += s
        failed, skipped = failed + f, skipped + k
        if points:
            spectra.append(points)
    warnings = (f"{failed} SPHEREx stacks or spectra failed and are left out.",) if failed else ()
    if skipped:
        note = (f"{skipped} SPHEREx frames could not be downloaded after several tries, "
                "so the spectrum is missing those measurements.")
        warnings += (note,)
    if not passes:
        warnings += ("No SPHEREx passes were found at this position.",)
    warnings += tuple(flag_reasons(spectra))
    return Collected(tuple(stacks), tuple(spectra), warnings, failed=failed + skipped > 0)


def ordered(items: Sequence[tuple[str, Stack]]) -> list[tuple[str, Stack]]:
    """Stacks sorted by time, then band id, so output is deterministic."""
    return sorted(items, key=lambda it: (it[1].mjd, it[0]))
