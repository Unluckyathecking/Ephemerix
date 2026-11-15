"""Run the Solar System body mode for one body: track, photometry, controls, spectra, stacks.

Every stage is timed (wall seconds) into `BodyRun.timings` for the evidence in the PR.
Units: mJy, micrometres, MJD, degrees.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

from pxs.spectra import iso_date
from pxs.spherex.net import TransientError
from pxs.spherex.types import Pass, SpecPoint

from .bands import Depth, band_depths
from .bodies import Body
from .controls import Control, run_control
from .horizons import HorizonsError
from .phot import BANDS, BandFlux, Measured, all_bands, measure_pass, read_visits, subtract
from .solar import RPoint, reflectance
from .stacks import SkyFixed, body_centred, read_half, sky_fixed
from .track import Track, Visit, find_visits, passes_of

log = logging.getLogger(__name__)

MIN_PASS_FRAMES = 6  # passes with fewer read frames are reported but not analysed
# Detection rule, calibrated on offset control tracks:
# S/N >= DETECTION_SNR in DETECTION_BANDS control-corrected bands; when fewer bands could
# be measured at all (a saturated bright body), SINGLE_BAND_SNR in the one there is. On
# empty control passes the old rule (best band S/N >= 5) fired on 39 of 551 (7%), this
# rule on 6 of 551 (1.1%); the campaign's 12 arcsec position gate takes that to 0.7%.
DETECTION_SNR = 5.0
DETECTION_BANDS = 2
SINGLE_BAND_SNR = 50.0
DETECTED, MARGINAL, NOT_DETECTED = "detected", "marginal", "not detected"
SEARCH_SHARE = 0.4  # of a run's time budget, at most, for SIA searches past the index end
HORIZONS_DOWN = ("JPL Horizons, which gives the body's position, did not answer, so no "
                 "SPHEREx exposures could be searched. Try again later.")
# Horizons unreachable, timing out after retries, or answering without an ephemeris.
EPHEMERIS_ERRORS = (HorizonsError, TransientError, requests.RequestException)


def pass_outcome(snrs: Sequence[float]) -> str:
    """DETECTED, MARGINAL (S/N >= DETECTION_SNR in one band only: consistent with noise in
    these fields) or NOT_DETECTED, from a pass's control-corrected band S/N values."""
    s = sorted((x for x in snrs if math.isfinite(x)), reverse=True)
    if not s or s[0] < DETECTION_SNR:
        return NOT_DETECTED
    if len(s) < DETECTION_BANDS:  # the other bands could not be measured (saturation)
        return DETECTED if s[0] >= SINGLE_BAND_SNR else MARGINAL
    return DETECTED if s[DETECTION_BANDS - 1] >= DETECTION_SNR else MARGINAL


@dataclass(frozen=True)
class PassResult:
    """Everything measured in one survey pass."""

    pas: Pass
    measured: tuple[Measured, ...]
    bands: tuple[BandFlux, ...]
    control: Control | None
    corrected: tuple[BandFlux, ...]  # body minus control
    reflectance: tuple[RPoint, ...]
    depths: tuple[Depth, ...]
    body_stacks: tuple = ()  # (band id, Stack)
    sky: SkyFixed | None = None
    sky_band: str = ""
    n_failed: int = 0

    @property
    def points(self) -> list[SpecPoint]:
        return [m.point for m in self.measured]

    @property
    def best(self) -> BandFlux | None:
        ok = [b for b in self.corrected if math.isfinite(b.snr)]
        return max(ok, key=lambda b: b.snr) if ok else None

    @property
    def outcome(self) -> str:
        return pass_outcome([b.snr for b in self.corrected])

    @property
    def detected(self) -> bool:
        return self.outcome == DETECTED

    @property
    def candidate(self) -> bool:
        """Best band at S/N >= DETECTION_SNR: detected or marginal (the rule before Nov 2026)."""
        return self.outcome != NOT_DETECTED


@dataclass(frozen=True)
class BodyRun:
    """The result of `run_body`."""

    body: Body
    track: Track | None = None
    passes: tuple[PassResult, ...] = ()
    skipped_passes: tuple[tuple[Pass, int], ...] = ()  # (pass, candidate frames) not analysed
    timings: dict[str, float] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    stopped_early: bool = False  # the time budget ran out before every pass was measured


Timings = dict[str, float]
Progress = Callable[[str, float], None]  # (stage, fraction done 0-1)


def _timed(timings: Timings, stage: str, fn: Callable):
    """fn(), with its wall time (s) added to timings[stage]."""
    t0 = time.perf_counter()
    try:
        return fn()
    finally:
        timings[stage] = round(timings.get(stage, 0.0) + time.perf_counter() - t0, 1)


def control_corrected_points(points: list[SpecPoint], control: Control | None) -> list[dict]:
    """Spectrum points (manifest style) with each band's control flux subtracted.

    The control error is not added to each point (it is shared by every point of a band);
    it is carried in the band fluxes instead.
    """
    out = []
    for p in points:
        band = next((b for b, (lo, hi) in BANDS.items() if lo <= p.wl_um < hi), None)
        c = next((x for x in (control.bands if control else ()) if x.band == band), None)
        off = c.flux_mjy if c is not None and c.n and math.isfinite(c.flux_mjy) else 0.0
        ok = not p.flagged and math.isfinite(p.flux_mjy) and math.isfinite(p.err_mjy)
        out.append({"wl_um": p.wl_um, "bw_um": p.bw_um, "flux": p.flux_mjy - off if ok else None,
                    "err": p.err_mjy if ok else None, "flagged": not ok, "detector": p.detector})
    return out


def analyse_pass(timings: Timings, pas: Pass, visits: list[Visit], with_stacks: bool,
                 with_control: bool) -> PassResult | None:
    half = read_half()
    read, failed = _timed(timings, "read stamps", lambda: read_visits(visits, half))
    if len(read) < MIN_PASS_FRAMES:
        return None
    measured = tuple(_timed(timings, "photometry", lambda: measure_pass(read)))
    bands = tuple(all_bands([m.point for m in measured]))
    control = _timed(timings, "controls", lambda: run_control(visits, half)) if with_control else None
    corrected = tuple(subtract(b, c) for b, c in zip(bands, control.bands)) if control else bands
    refl, _ = reflectance(control_corrected_points([m.point for m in measured], control))
    depths = tuple(band_depths(refl))
    res = PassResult(pas, measured, bands, control, corrected, tuple(refl), depths,
                     n_failed=failed)
    if not with_stacks or not res.detected:
        return res
    best = res.best.band  # type: ignore[union-attr]

    def make() -> tuple[tuple, SkyFixed | None]:
        bc = tuple((b, s) for b, w in BANDS.items()
                   if (s := body_centred(measured, b, w)) is not None)
        return bc, sky_fixed(measured, best, BANDS[best])

    bc, sky = _timed(timings, "stacks", make)
    return PassResult(pas, measured, bands, control, corrected, tuple(refl), depths, bc, sky,
                      best, failed)


def _search_warnings(track: Track) -> list[str]:
    out = []
    if track.failed_cones:
        out.append(f"The archive did not answer for {track.failed_cones} of "
                   f"{track.n_cones} track segments, so some exposures may be missing.")
    if track.unsearched_after_mjd is not None:
        out.append(f"Exposures after {iso_date(track.unsearched_after_mjd)[:10]} were not "
                   "searched: the local SPHEREx frame index ends there.")
    return out


def _say(progress: Progress | None, stage: str, fraction: float) -> None:
    if progress is not None:
        progress(stage, fraction)


def run_body(body: Body, mjd_stop: float | None = None, with_stacks: bool = True,
             with_control: bool = True, max_passes: int | None = None,
             progress: Progress | None = None, deadline: float | None = None,
             clock: Callable[[], float] = time.monotonic) -> BodyRun:
    """Find the body's SPHEREx exposures and measure every pass.

    `progress(stage, fraction)` is told what is being done. With a `deadline` (on `clock`),
    a pass is only started when the longest pass so far would still end before it; the
    passes already measured are kept and the rest are reported as not measured.
    """
    timings: Timings = {}
    stop = mjd_stop or (datetime.now(UTC) - datetime(1858, 11, 17, tzinfo=UTC)).days - 1.0
    _say(progress, "Asking JPL Horizons where the body was and searching SPHEREx exposures",
         0.02)
    # Archive searches past the index end may use at most SEARCH_SHARE of the time left.
    search = ({} if deadline is None else
              {"sia_deadline": time.monotonic() + SEARCH_SHARE * (deadline - clock())})
    try:
        track = _timed(timings, "ephemeris and frame search",
                       lambda: find_visits(body.horizons, stop, **search))
    except EPHEMERIS_ERRORS:
        log.exception("ephemeris for %s failed", body.horizons)
        return BodyRun(body, None, (), (), timings, (HORIZONS_DOWN,))
    warnings = _search_warnings(track)
    passes, skipped = [], []
    groups = passes_of(track.visits)
    groups = groups[:max_passes] if max_passes else groups
    longest, stopped = 0.0, False
    for i, (pas, visits) in enumerate(groups):
        if deadline is not None and clock() + longest > deadline:
            warnings.append(f"Stopped after {i} of {len(groups)} SPHEREx passes so the view "
                            "could finish in time; the other passes were not measured.")
            stopped = True
            break
        _say(progress, f"Measuring pass {i + 1} of {len(groups)} "
             f"({iso_date(pas.mjd_start)[:10]}, {len(visits)} exposures)",
             0.1 + 0.85 * i / max(len(groups), 1))
        t0 = clock()
        res = analyse_pass(timings, pas, visits, with_stacks, with_control)
        longest = max(longest, clock() - t0)
        if res is None:
            skipped.append((pas, len(visits)))
            continue
        passes.append(res)
        if res.n_failed:
            warnings.append(f"{res.n_failed} exposures could not be read and were skipped.")
    if not passes and not stopped:
        warnings.append("SPHEREx has no usable exposures of this body yet.")
    return BodyRun(body, track, tuple(passes), tuple(skipped), timings, tuple(warnings),
                   stopped)
