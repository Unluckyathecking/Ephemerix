"""Injection-recovery: completeness against flux and rate, measured with the real search.

Each run injects a batch of synthetic movers into the real native stamps of the search
pass, rebuilds the search layers, runs the same core search, and matches detections to
injections. A source is found at its position when a detection with clipped S/N >= threshold
starts within MATCH_PX of it, and recovered when that detection's track also stays within
MATCH_PX of the injected track in at least half the frames (the rate is right). Detections
found at an injection's position never count as extras (unmatched detections).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .candidates import Detection, track_xy
from .core import THRESHOLD, CoreResult, run_core
from .field import FieldData, search_layers
from .inject import Synthetic, Template, draw_sources, injector, position_px

log = logging.getLogger(__name__)

MATCH_PX = 2.0


@dataclass(frozen=True)
class Trial:
    """One injected source and its outcome: recovered S/N and flux (NaN if missed).
    at_position: a detection above threshold started at the source (rate not checked)."""

    source: Synthetic
    rate_px_day: float
    recovered: bool
    snr: float
    flux_mjy: float
    at_position: bool = False


def injected_track(src: Synthetic, core: CoreResult) -> np.ndarray:
    """(2, n) grid-pixel positions of an injected source at the cube's frame times."""
    pos = [position_px(src, core.geom, m) for m in core.cube.mjd]
    return np.array(pos).T


def match(sources: list[Synthetic], core: CoreResult,
          threshold: float = THRESHOLD) -> tuple[list[Trial], list[Detection]]:
    """(per-source outcomes, detections above threshold that start at no injection)."""
    dets = [d for d in core.detections if d.snr >= threshold]
    used: set[int] = set()
    at_any: set[int] = set()
    out = []
    for src in sources:
        truth = injected_track(src, core)
        best: Detection | None = None
        best_k = -1
        near = [k for k, d in enumerate(dets) if math.hypot(d.x - src.x, d.y - src.y) <= MATCH_PX]
        at_any.update(near)
        for k in near:
            d = dets[k]
            if k in used:
                continue
            close = np.hypot(*(track_xy(core.trials, d) - truth)) <= MATCH_PX
            if np.mean(close) >= 0.5 and (best is None or d.snr > best.snr):
                best, best_k = d, k
        if best is not None:
            used.add(best_k)
        rate = math.hypot(src.vx, src.vy)
        out.append(Trial(src, rate, best is not None, best.snr if best else math.nan,
                         best.flux_mjy if best else math.nan, at_position=bool(near)))
    extra = [d for k, d in enumerate(dets) if k not in at_any]
    return out, extra


def run_injections(fd: FieldData, n_runs: int, per_run: int, flux_range_mjy: tuple[float, float],
                   d_range_au: tuple[float, float], template: Template,
                   seed: int = 1, base: CoreResult | None = None,
                   collect: Callable[[CoreResult, list[Synthetic]], None] | None = None
                   ) -> tuple[list[Trial], list[int]]:
    """All injection outcomes, and the number of unmatched detections in each run.
    `base` is the search of the same field without injections (run here if not given);
    `collect` sees every injected run (used to build the vetting training set)."""
    rng = np.random.default_rng(seed)
    if base is None:
        base = run_core(fd.search, fd.refs, fd.grid.center_ra, fd.grid.center_dec,
                        fd.grid.pixscale_arcsec, with_null=False)
    real = [(d.x, d.y) for d in base.above()]
    trials: list[Trial] = []
    extras: list[int] = []
    for r in range(n_runs):
        srcs = draw_sources(rng, per_run, fd.grid, base.geom, flux_range_mjy, d_range_au)
        layers = search_layers(fd, injector(srcs, base.geom, fd.grid, template))
        core = run_core(layers, fd.refs, fd.grid.center_ra, fd.grid.center_dec,
                        fd.grid.pixscale_arcsec, with_null=False, tgrid=base.tgrid)
        got, extra = match(srcs, core)
        if collect is not None:
            collect(core, srcs)
        trials.extend(got)
        extras.append(sum(all(math.hypot(d.x - x, d.y - y) > MATCH_PX for x, y in real)
                          for d in extra))
        log.info("injection run %d/%d: %d/%d recovered", r + 1, n_runs,
                 sum(t.recovered for t in got), len(got))
    return trials, extras


@dataclass(frozen=True)
class Curve:
    """Completeness per flux bin (mJy at the reference wavelength), with counts."""

    flux_mjy: np.ndarray
    completeness: np.ndarray
    n: np.ndarray

    def flux_at(self, level: float) -> float:
        """Faintest flux above which completeness stays >= level (interpolated), mJy."""
        c = self.completeness
        ok = np.flatnonzero(np.isfinite(c))
        if ok.size == 0 or c[ok[-1]] < level:
            return math.nan
        below = [i for i in ok if c[i] < level]
        if not below:
            return float(self.flux_mjy[ok[0]])
        i = below[-1]
        j = next((k for k in ok if k > i), None)
        if j is None:
            return math.nan
        lf = np.interp(level, [c[i], c[j]], np.log([self.flux_mjy[i], self.flux_mjy[j]]))
        return float(np.exp(lf))


def curve(trials: list[Trial], n_bins: int = 12, rate_range: tuple[float, float] | None = None
          ) -> Curve:
    """Completeness in log-flux bins, optionally for one range of rates (px/day)."""
    ts = [t for t in trials if rate_range is None or rate_range[0] <= t.rate_px_day < rate_range[1]]
    if not ts:
        return Curve(np.array([]), np.array([]), np.array([]))
    f = np.array([t.source.flux_mjy for t in ts])
    rec = np.array([t.recovered for t in ts])
    edges = np.exp(np.linspace(np.log(f.min()), np.log(f.max()) * (1 + 1e-9), n_bins + 1))
    idx = np.clip(np.digitize(f, edges) - 1, 0, n_bins - 1)
    n = np.bincount(idx, minlength=n_bins)
    k = np.bincount(idx, weights=rec, minlength=n_bins)
    with np.errstate(invalid="ignore", divide="ignore"):
        comp = np.where(n > 0, k / n, np.nan)
    return Curve(np.sqrt(edges[:-1] * edges[1:]), comp, n)
