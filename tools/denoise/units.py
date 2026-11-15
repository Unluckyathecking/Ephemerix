"""Container work: training cubes, validation diagnostics, and the gate units.

Arm "base" is pxs.movers.core.run_core unchanged (the current method). Arm "den" is the same
sequence of pipeline functions with one change: the model's prediction is subtracted from
the difference cube (and the reference's variance removed with it) before the matched
filter. All arms see the same frames, references, masks, trial grid, injections (the
campaign's seeds) and detection code. GATE_ARMS are the registered gate's two arms; the
other variance choices exist only for the follow-up described in README.md. Detections are kept down to S/N 5 so thresholds can be
matched in false-alarm rate afterwards. Everything returned is plain JSON-able Python.
Heavy: run through modal_denoise.py.
"""

from __future__ import annotations

import dataclasses
import itertools
import logging
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SIZE_ARCMIN = 20.0
STATIC_BLANK = 0.3  # deep reference below this many frame sigma: no static source seen
# Arm name -> how the "den" cube's variance is formed (None: the baseline, no model).
#   reference_removed: pipeline variance minus the matched reference's term (the gate's arm)
#   pipeline: pipeline variance unchanged
#   smoothed: reference_removed, then a 7x7 median, so a pixel's weight no longer follows
#             its own noise (the Level 2 variance contains each pixel's measured signal)
GATE_ARMS: dict[str, str | None] = {"base": None, "den": "reference_removed"}
SELECT_ARMS: dict[str, str | None] = GATE_ARMS | {"den_pipeline": "pipeline",
                                                  "den_smoothed": "smoothed"}
VAR_SMOOTH_PX = 7


def passes_to_use(ra: float, dec: float) -> list[int]:
    """Indices (into usable passes) of up to three passes that have a reference pass: the
    first, the middle and the last. Cubes of different passes share no search frame."""
    from pxs.movers.field import SEARCH_DETECTORS, reference_frames, usable_passes
    from pxs.movers.frames import field_passes

    passes = usable_passes(field_passes(ra, dec))
    ok = [i for i, p in enumerate(passes)
          if reference_frames(passes, p, SEARCH_DETECTORS)[0]
          and sum(f.detector in SEARCH_DETECTORS for f in p.frames) >= 10]
    return sorted({ok[0], ok[len(ok) // 2], ok[-1]}) if ok else []


def training_cubes(name: str, ra: float, dec: float, out_dir: Path) -> dict[str, Any]:
    """Write <name>__p<k>.npz (x float16, scal float32) for each used pass of one field."""
    from pxs.movers.difference import difference_cube
    from pxs.movers.field import load_field

    from .features import build

    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for k in passes_to_use(ra, dec):
        fd = load_field(ra, dec, SIZE_ARCMIN, k)
        cube = difference_cube(fd.search, fd.refs)
        x, scal, _, _ = build(fd.search, fd.refs, cube)
        valid = x[:, 1] > 0
        np.savez_compressed(out_dir / f"{name}__p{k}.npz", x=x.astype(np.float16), scal=scal)
        written.append({"pass": k, "n_frames": len(x), "n_ref": len(fd.refs),
                        "valid_fraction": float(valid.mean()),
                        "t_rms": float(np.sqrt(np.mean(x[:, 0][valid] ** 2))),
                        "mjd": [float(cube.mjd.min()), float(cube.mjd.max())]})
        log.info("%s pass %d: %s", name, k, written[-1])
    return {"name": name, "ra": ra, "dec": dec, "cubes": written,
            "seconds": float(time.time() - t0)}


def load_model(path: Path) -> Any:
    import torch

    from .model import blind_check, build_model

    model = build_model()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    leak = blind_check(model)
    if leak != 0.0:
        raise AssertionError(f"blind spot leaks: {leak}")
    return model.eval()


def _median_smoothed(var: np.ndarray) -> np.ndarray:
    """Each frame's variance replaced by its VAR_SMOOTH_PX-wide median (NaN kept)."""
    from scipy.ndimage import median_filter

    out = np.full_like(var, np.nan)
    for i, v in enumerate(var):
        fin = np.isfinite(v)
        if fin.any():
            filled = np.where(fin, v, np.median(v[fin]))
            out[i] = np.where(fin, median_filter(filled, size=VAR_SMOOTH_PX, mode="nearest"),
                              np.nan)
    return out


def corrected_cube(search: Any, refs: Any, model: Any,
                   variance: str = "reference_removed") -> tuple[Any, dict[str, float]]:
    """The pipeline's difference cube minus the model's prediction, and how much of the
    whitened variance the prediction removed (all valid pixels, and pixels on references
    brighter than 3 sigma). `variance`: see GATE_ARMS."""
    from pxs.movers.difference import difference_cube

    from .features import build
    from .model import predict

    cube = difference_cube(search, refs)
    x, scal, sig, rvar = build(search, refs, cube)
    g = predict(model, x, scal)
    ok = x[:, 1] > 0
    with np.errstate(invalid="ignore"):
        t = np.where(ok, cube.diff / sig, 0.0)
        diff = (cube.diff - g * sig).astype(np.float32)
        # The model's sky estimate now stands in for the matched reference, so the
        # reference's variance leaves the budget (see README: decided on validation fields).
        var = np.where(np.isfinite(rvar) & (cube.var - rvar > 0), cube.var - rvar, cube.var)
    if variance == "pipeline":
        var = cube.var
    elif variance == "smoothed":
        var = _median_smoothed(var)
    elif variance != "reference_removed":
        raise ValueError(f"unknown variance mode: {variance}")
    lo, hi = np.percentile(t[ok], [0.5, 99.5])
    core = ok & (t > lo) & (t < hi)  # the central 99%: not dominated by a few outliers
    star = core & (np.sinh(np.abs(x[:, 3])) > 3.0)
    stats = {"ev_all": 1.0 - float(np.mean((t - g)[core] ** 2) / np.mean(t[core] ** 2)),
             "ev_star": 1.0 - float(np.mean((t - g)[star] ** 2) / np.mean(t[star] ** 2))
             if star.any() else math.nan,
             "g_rms": float(np.sqrt(np.mean(g[ok] ** 2))),
             "star_fraction": float(star.sum() / max(core.sum(), 1))}
    return dataclasses.replace(cube, diff=diff, var=var.astype(np.float32)), stats


def variance_shares(name: str, ra: float, dec: float, pass_index: int, model: Any,
                    probes: tuple[tuple[int, int], ...] = ()) -> dict[str, Any]:
    """On one field: the share of the whitened difference-image variance removed by the
    model, and by two changes that need no model: not subtracting the reference at all, and
    subtracting the deep all-wavelength reference instead of the matched one. Central 99% of
    valid pixels, split into blank sky and star pixels (deep reference > 3 frame sigma)."""
    from pxs.movers.difference import difference_cube
    from pxs.movers.field import load_field

    from .features import _ref_stats, build
    from .model import predict

    fd = load_field(ra, dec, SIZE_ARCMIN, pass_index)
    cube = difference_cube(fd.search, fd.refs)
    x, scal, sig, _ = build(fd.search, fd.refs, cube)
    g = {"model": predict(model, x, scal), "no_reference": np.zeros_like(sig),
         "deep_reference": np.zeros_like(sig)}
    rshare = np.zeros_like(sig)
    for i, layer in enumerate(fd.search):
        same = [r for r in fd.refs if r.frame.detector == layer.frame.detector]
        stack = (np.stack([r.image for r in same]), np.stack([r.variance for r in same]),
                 np.stack([r.wave for r in same])) if same else None
        ref, rvar, _, deep = _ref_stats(layer, stack)
        with np.errstate(invalid="ignore", divide="ignore"):
            g["no_reference"][i] = np.nan_to_num(-ref / sig[i])
            g["deep_reference"][i] = np.nan_to_num(-(ref - deep) / sig[i])
            rshare[i] = np.nan_to_num(rvar / cube.var[i])
    ok = x[:, 1] > 0
    t = x[:, 0]
    lo, hi = np.percentile(t[ok], [0.5, 99.5])
    core = ok & (t > lo) & (t < hi)
    star = core & (np.sinh(np.abs(x[:, 3])) > 3.0)
    out: dict[str, Any] = {"name": name, "pass_index": pass_index, "n_frames": len(x),
                           "reference_variance_share": float(rshare[core].mean()),
                           "star_fraction": float(star.sum() / core.sum())}
    for key, sel in (("blank", core & ~star), ("star", star), ("all", core)):
        out[key] = {k: 1.0 - float(np.mean((t - v)[sel] ** 2) / np.mean(t[sel] ** 2))
                    for k, v in g.items()}
    # Noise calibration against the reference's share of the variance budget: robust scatter
    # of the whitened image in quartiles of that share, for the baseline, for the model with
    # the variance unchanged, and for the model with the reference variance removed.
    def scatter(v: np.ndarray) -> float:
        return float(1.4826 * np.median(np.abs(v - np.median(v))))

    edges = np.percentile(rshare[core], [0, 25, 50, 75, 100])
    resid = t - g["model"]
    out["calibration"] = []
    for lo_e, hi_e in itertools.pairwise(edges):
        sel = core & (rshare >= lo_e) & (rshare <= hi_e)
        out["calibration"].append({
            "share": float(rshare[sel].mean()), "base": scatter(t[sel]),
            "model_same_var": scatter(resid[sel]),
            "model_less_var": scatter(resid[sel] / np.sqrt(1.0 - rshare[sel]))})
    # Static residual: per sky pixel, the mean whitened value over the pass in units of its
    # error (pixels valid in >= 20 frames). A static-sky estimate that is biased at some
    # source leaves the same residual in every frame, which slow tracks then stack.
    nv = ok.sum(axis=0)
    deep = np.where(ok, np.sinh(np.abs(x[:, 3])), 0.0).sum(axis=0) / np.maximum(nv, 1)

    def zmap(v: np.ndarray) -> np.ndarray:
        return np.where(nv >= 20, np.where(ok, v, 0.0).sum(axis=0) / np.sqrt(np.maximum(nv, 1)),
                        np.nan)

    zs = {"base": zmap(t), "model": zmap(resid / np.sqrt(1.0 - np.minimum(rshare, 0.95)))}
    blank = deep < STATIC_BLANK
    out["static"] = {"blank_fraction": float(blank[nv >= 20].mean())}
    for k, z in zs.items():
        fin = np.isfinite(z)
        out["static"][k] = {
            "scatter": scatter(z[fin]), "gt5": int((np.abs(z[fin]) > 5).sum()),
            "gt7": int((np.abs(z[fin]) > 7).sum()),
            "gt5_blank": int((np.abs(z[fin & blank]) > 5).sum()),
            "gt7_blank": int((np.abs(z[fin & blank]) > 7).sum())}
    out["probes"] = [{"xy": [px, py], "deep": float(deep[py, px]),
                      "base": float(np.nanmax(np.abs(zs["base"][py - 2:py + 3, px - 2:px + 3]))),
                      "model": float(np.nanmax(np.abs(zs["model"][py - 2:py + 3, px - 2:px + 3])))}
                     for px, py in probes]
    return _plain(out)


def run_arm(search: Any, refs: Any, ra: float, dec: float, pixscale: float, tgrid: Any,
            model: Any, variance: str | None, with_null: bool) -> tuple[Any, dict[str, float]]:
    """run_core for variance None; otherwise run_core's steps on the corrected cube."""
    from pxs.movers.candidates import detect
    from pxs.movers.core import SEED_THRESHOLD, CoreResult, run_core
    from pxs.movers.geometry import pass_geometry
    from pxs.movers.matched import planes, reflected_template
    from pxs.movers.search import make_trials, run_search

    if variance is None:
        return run_core(search, refs, ra, dec, pixscale, with_null=with_null, tgrid=tgrid), {}
    cube, stats = corrected_cube(search, refs, model, variance)
    cube = cube.with_template(reflected_template(cube.wave_um))
    pl = planes(cube)
    geom = pass_geometry(ra, dec, cube.mjd, pixscale)
    trials = make_trials(geom, tgrid)
    maps = run_search(pl, trials)
    dets = detect(pl, maps, trials, geom.dt, SEED_THRESHOLD)
    null: list[Any] = []
    if with_null:
        nmaps = run_search(pl, trials, mirror=True)
        null = detect(pl, nmaps, trials, geom.dt, SEED_THRESHOLD, mirror=True)
    return CoreResult(cube, pl, geom, tgrid, trials, maps, tuple(dets), tuple(null)), stats


def forced_flux(core: Any, src: Any) -> tuple[float, float]:
    """(flux, error) in mJy at the reference wavelength, summed along the injected track
    itself (nearest pixel per frame, no clipping, no detection needed)."""
    from pxs.movers.completeness import injected_track
    from pxs.spherex import config

    tr = injected_track(src, core)
    xi, yi = np.rint(tr[0]).astype(int), np.rint(tr[1]).astype(int)
    n, h, w = core.planes.psi.shape
    inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    idx = np.arange(n)[inside]
    sp = float(core.planes.psi[idx, yi[inside], xi[inside]].sum())
    sf = float(core.planes.phi[idx, yi[inside], xi[inside]].sum())
    if sf <= 0:
        return math.nan, math.nan
    return sp / sf * config.MJYSR_TO_MJY, config.MJYSR_TO_MJY / math.sqrt(sf)


def _setup(ra: float, dec: float, pass_index: int) -> tuple[Any, Any, Any]:
    from pxs.movers.core import prepare
    from pxs.movers.field import load_field
    from pxs.movers.geometry import trajectory_grid

    fd = load_field(ra, dec, SIZE_ARCMIN, pass_index)
    _, _, geom = prepare(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec)
    return fd, geom, trajectory_grid(geom)


def gate_base(name: str, ra: float, dec: float, pass_index: int, model: Any,
              arms: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Real search and mirrored null in every arm; every detection >= 5 as [x, y, snr]."""
    t0 = time.time()
    arms = GATE_ARMS if arms is None else arms
    fd, _, tgrid = _setup(ra, dec, pass_index)
    out: dict[str, Any] = {"name": name, "unit": "base", "pass_index": pass_index,
                           "arms": arms}
    for arm, variance in arms.items():
        core, stats = run_arm(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec, tgrid,
                              model, variance, with_null=True)
        out[arm] = {"real": [[d.x, d.y, round(d.snr, 3)] for d in core.detections],
                    "null": [[d.x, d.y, round(d.snr, 3)] for d in core.null_detections],
                    "noise_scale_median": float(np.nanmedian(core.planes.noise_scale)),
                    "search_s": core.maps.seconds, "stats": stats}
        out["n_frames"], out["n_trials"] = len(core.cube), len(core.trials)
    out["seconds"] = time.time() - t0
    return _plain(out)


def gate_injections(name: str, ra: float, dec: float, pass_index: int, runs: list[int],
                    model: Any, arms: dict[str, str | None] | None = None) -> dict[str, Any]:
    """The campaign's injection runs (same seeds, so the same sources) searched in every arm.
    Per source and arm: matched S/N at threshold 5 (None if unmatched) and forced flux."""
    from pxs.movers.campaign import D_RANGE_AU, FLUX_RANGE_MJY, PER_RUN
    from pxs.movers.completeness import match
    from pxs.movers.core import SEED_THRESHOLD
    from pxs.movers.field import search_layers
    from pxs.movers.inject import draw_sources, injector
    from pxs.movers.matched import reflected_template

    t0 = time.time()
    arms = GATE_ARMS if arms is None else arms
    fd, geom, tgrid = _setup(ra, dec, pass_index)
    rows = []
    for run in runs:
        seed = 1000 * sum(map(ord, name)) + run  # campaign.injection_unit's seed
        srcs = draw_sources(np.random.default_rng(seed), PER_RUN, fd.grid, geom,
                            FLUX_RANGE_MJY, D_RANGE_AU)
        layers = search_layers(fd, injector(srcs, geom, fd.grid, reflected_template))
        per_arm = {}
        for arm, variance in arms.items():
            core, _ = run_arm(layers, fd.refs, ra, dec, fd.grid.pixscale_arcsec, tgrid, model,
                              variance, with_null=False)
            got, _ = match(srcs, core, threshold=SEED_THRESHOLD)
            per_arm[arm] = [(t, forced_flux(core, t.source)) for t in got]
        for k, s in enumerate(srcs):
            row: dict[str, Any] = {"run": run, "flux_mjy": s.flux_mjy, "d_au": s.d_au,
                                   "x": s.x, "y": s.y, "rate": math.hypot(s.vx, s.vy)}
            for arm in arms:
                t, (ff, fe) = per_arm[arm][k]
                row[arm] = {"snr": t.snr if t.recovered else None, "at": t.at_position,
                            "forced": ff if math.isfinite(ff) else None,
                            "forced_err": fe if math.isfinite(fe) else None}
            rows.append(row)
        log.info("%s run %d: recovered >= 7: base %d, den %d of %d", name, run,
                 *(sum((r[a]["snr"] or 0) >= 7 for r in rows if r["run"] == run)
                   for a in ("base", "den")), len(srcs))
    return _plain({"name": name, "unit": "inj", "runs": runs, "arms": arms, "sources": rows,
                   "seconds": time.time() - t0})


def _plain(obj: Any) -> Any:
    import json

    return json.loads(json.dumps(obj, default=float))
