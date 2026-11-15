"""search_field(center, size, pass) -> SearchResult: the whole search for one field-pass."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import classify
from .candidates import Detection
from .completeness import curve, run_injections
from .core import THRESHOLD, CoreResult, frames_on_track, rate_of, run_core
from .field import MAX_SPAN_DAYS, FieldData, load_field
from .geometry import D_MAX_AU, implied_distance_range
from .limits import distance_curves, motion_distance, statement, vmag_from_1um
from .matched import reflected_template
from .render import write_stamps
from .result import (
    LABEL_INCONSISTENT,
    LABEL_KNOWN,
    LABEL_STAR,
    LABEL_UNVETTED,
    Candidate,
    Limit,
    SearchResult,
)
from .search import MIN_MOTION_PX
from .vet import bright_stars, false_alarm_probability, field_known_objects, match_known, near_star
from .vetdata import FEATURES, sample

log = logging.getLogger(__name__)

MIN_HALF_SNR = 2.0  # each half of the pass must contribute (kills one-sided artefacts)
INJ_FLUX_MJY = (0.02, 0.4)  # injected flux range at 1 um (AB 20.9-17.9)
INJ_D_AU = (30.0, 1000.0)


def consistent(d: Detection) -> bool:
    return min(d.snr_first, d.snr_second) >= MIN_HALF_SNR and d.max_frame_share < 0.5


def _candidate(core: CoreResult, fd: FieldData, d: Detection, rank: int, null: list[float],
               stars, knowns) -> Candidate:
    vx, vy, _ = rate_of(core, d)
    ra, dec = (float(v) for v in fd.grid.wcs().all_pix2world(d.x, d.y, 0))
    scale = fd.grid.pixscale_arcsec / 24.0  # px/day -> arcsec/hour
    pa = math.degrees(math.atan2(-vx, -vy)) % 360.0  # +x is west, +y is south
    on = frames_on_track(core, d)
    bands = {f"D{k}": int(np.sum(on & (core.cube.detector == k)))
             for k in sorted(set(core.cube.detector.tolist()))}
    known = match_known(knowns, ra, dec)
    if known is not None:
        label = LABEL_KNOWN
    elif near_star(stars, d.x, d.y):
        label = LABEL_STAR
    elif not consistent(d):
        label = LABEL_INCONSISTENT
    else:
        label = LABEL_UNVETTED
    return Candidate(
        rank=rank, label=label, ra=ra, dec=dec, mjd_mid=core.geom.t0,
        rate_arcsec_h=math.hypot(vx, vy) * scale, pa_deg=pa,
        distance_au=implied_distance_range(core.tgrid, vx, vy, core.geom),
        snr=d.snr, snr_unclipped=d.snr_raw, snr_first_half=d.snr_first,
        snr_second_half=d.snr_second, flux_ujy=d.flux_mjy * 1e3,
        flux_err_ujy=d.flux_err_mjy * 1e3, band_frames=bands,
        fap=false_alarm_probability(d.snr, null),
        known_name=known.name if known else None, known_vmag=known.vmag if known else None)


def _vet_scores(core: CoreResult, cands: list[Candidate]
                ) -> tuple[list[Candidate], dict | None]:
    """Advisory vetting scores from the committed model, if there is one; labels unchanged."""
    model = classify.load()
    if model is None:
        return cands, None
    dets = core.above(THRESHOLD)
    feats = np.array([sample(core, d)[1] for d in dets]).reshape(len(dets), len(FEATURES))
    scores = model.score(feats, FEATURES) if len(dets) else np.zeros(0)
    info = {"model": "logistic regression on track features", "features": list(model.features),
            "gate_passed": model.gate_passed, "trained_on": list(model.trained_on),
            "note": "advisory only: the score never changes a label or drops a candidate"}
    return [replace(c, vet_score=float(s)) for c, s in zip(cands, scores)], info


def measure_limit(fd: FieldData, core: CoreResult, n_runs: int, per_run: int,
                  seed: int) -> Limit:
    """Injection-recovery completeness and the limit statement for this field-pass."""
    trials, _ = run_injections(fd, n_runs, per_run, INJ_FLUX_MJY, INJ_D_AU, reflected_template,
                               seed=seed, base=core)
    c = curve(trials)
    f50, f90 = c.flux_at(0.5) * 1e3, c.flux_at(0.9) * 1e3
    v50, v90 = vmag_from_1um(f50), vmag_from_1um(f90)
    d_mot = min(motion_distance(core.geom, MIN_MOTION_PX), D_MAX_AU)
    return Limit(flux_ujy=list(c.flux_mjy * 1e3), completeness=list(c.completeness),
                 n_injected=[int(n) for n in c.n], flux50_ujy=f50, flux90_ujy=f90,
                 vmag50=v50, vmag90=v90, statement=statement(v50, d_mot),
                 distance_curves=distance_curves(v50, d_mot))


def search_field(center: tuple[float, float], size_arcmin: float = 20.0, pass_index: int = 0,
                 out_dir: Path | None = None, completeness_runs: int = 0,
                 per_run: int = 25, seed: int = 1) -> SearchResult:
    """Search one SPHEREx pass of a field for slow movers.

    center: (ra, dec) degrees; size_arcmin: field side; pass_index: index into the field's
    usable passes, oldest first. With out_dir, stamp PNGs are written there. With
    completeness_runs > 0, that many injection runs of per_run sources measure the limit.
    """
    t0 = time.time()
    fd = load_field(center[0], center[1], size_arcmin, pass_index)
    core = run_core(fd.search, fd.refs, center[0], center[1], fd.grid.pixscale_arcsec)
    null = [d.snr for d in core.null_detections]
    stars = bright_stars(fd.grid)
    knowns, kwarn = field_known_objects(fd.grid, core.geom.t0)
    cands = [_candidate(core, fd, d, k + 1, null, stars, knowns)
             for k, d in enumerate(core.above(THRESHOLD))]
    if out_dir is not None:
        cands = [replace(c, stamps=write_stamps(core, d, out_dir / "stamps", f"c{c.rank:02d}"))
                 for c, d in zip(cands, core.above(THRESHOLD))]
    cands, vet = _vet_scores(core, cands)
    t_search = time.time() - t0
    limit = measure_limit(fd, core, completeness_runs, per_run, seed) \
        if completeness_runs > 0 else None
    return SearchResult(
        center_ra=center[0], center_dec=center[1], size_arcmin=size_arcmin,
        pass_mjd=(float(core.cube.mjd.min()), float(core.cube.mjd.max())),
        n_frames=len(core.cube), n_reference_frames=len(fd.refs),
        n_reference_passes=fd.n_ref_passes, masked_fraction=core.cube.masked_fraction,
        n_trials=len(core.trials), threshold=THRESHOLD, min_motion_px=MIN_MOTION_PX,
        candidates=cands, null_peaks_above_threshold=len(core.above(THRESHOLD, null=True)),
        null_max_snr=max(null, default=float("nan")),
        timings_s={"read": fd.read_seconds, "search": core.maps.seconds,
                   "total_search": t_search, "completeness": time.time() - t0 - t_search},
        limit=limit, warnings=list(stars.warnings) + list(kwarn) + _window_warning(fd), vet=vet)


def _window_warning(fd: FieldData) -> list[str]:
    if not fd.n_dropped:
        return []
    return [(f"pass is longer than {MAX_SPAN_DAYS:.0f} days: searched the densest window, "
             f"{len(fd.search)} of {fd.n_pass_frames} frames")]
