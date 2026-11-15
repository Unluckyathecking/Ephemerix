"""Container work for the Planet Nine region pilot: pass pre-flight and the base search unit.

Injection units reuse pxs.movers.campaign.injection_unit unchanged. Everything returned is
plain JSON-able Python. Heavy: run through tools/p9_search/modal_p9.py.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SIZE_ARCMIN = 20.0
STAMP_CAP = 12  # stamps written for at most this many real peaks >= 7 per field


def choose_pass(summaries: list[dict[str, Any]]) -> int | None:
    """Index (into usable passes) of the pass with the most frames inside its densest
    16-day window, among passes that have a reference pass; earliest on ties."""
    ok = [s for s in summaries if s["has_reference"]]
    if not ok:
        return None
    best = max(ok, key=lambda s: (s["n_window"], -s["index"]))
    return int(best["index"])


def preflight(ra: float, dec: float) -> dict[str, Any]:
    """Usable passes of the field (search detectors) and the chosen one; reads no pixels."""
    from pxs.movers.field import (
        SEARCH_DETECTORS,
        reference_frames,
        search_window,
        usable_passes,
    )
    from pxs.movers.frames import field_passes

    passes = usable_passes(field_passes(ra, dec))
    out = []
    for i, p in enumerate(passes):
        fr = [f for f in p.frames if f.detector in SEARCH_DETECTORS]
        win = search_window(fr)
        refs, _ = reference_frames(passes, p, SEARCH_DETECTORS)
        out.append({"index": i, "mjd_start": p.mjd_start, "mjd_end": p.mjd_end,
                    "n_frames": len(fr), "n_window": len(win),
                    "window_days": (win[-1].mjd - win[0].mjd) if win else 0.0,
                    "has_reference": bool(refs)})
    return {"passes": out, "chosen": choose_pass(out)}


def nearest_px(xs: np.ndarray, ys: np.ndarray, x: float, y: float) -> float | None:
    if not np.size(xs):
        return None
    return float(np.min(np.hypot(np.asarray(xs) - x, np.asarray(ys) - y)))


def base_unit(name: str, ra: float, dec: float, pass_index: int,
              stamp_dir: Path | None = None) -> dict[str, Any]:
    """Real search and mirrored null for one tile, with every real peak >= 7 labelled."""
    from pxs.movers.api import _candidate, consistent
    from pxs.movers.campaign import _plain, field_meta
    from pxs.movers.core import THRESHOLD, run_core
    from pxs.movers.field import load_field
    from pxs.movers.limits import motion_distance
    from pxs.movers.render import write_stamps
    from pxs.movers.search import MIN_MOTION_PX
    from pxs.movers.vet import bright_stars, field_known_objects

    t0, c0 = time.time(), time.process_time()
    fd = load_field(ra, dec, SIZE_ARCMIN, pass_index)
    core = run_core(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec)
    null = [d.snr for d in core.null_detections]
    stars = bright_stars(fd.grid)
    knowns, kwarn = field_known_objects(fd.grid, core.geom.t0)
    peaks = []
    for k, d in enumerate(core.above(THRESHOLD)):
        c = _candidate(core, fd, d, k + 1, null, stars, knowns)
        rec = {"rank": c.rank, "label": c.label, "x": d.x, "y": d.y, "ra": c.ra,
               "dec": c.dec, "snr": c.snr, "snr_unclipped": c.snr_unclipped,
               "snr_first_half": c.snr_first_half, "snr_second_half": c.snr_second_half,
               "max_frame_share": d.max_frame_share, "n_frames": d.n_frames,
               "n_clipped": d.n_clipped, "half_consistent": consistent(d),
               "flux_ujy": c.flux_ujy, "flux_err_ujy": c.flux_err_ujy,
               "rate_arcsec_h": c.rate_arcsec_h, "pa_deg": c.pa_deg,
               "distance_au": list(c.distance_au), "fap": c.fap,
               "known_name": c.known_name, "band_frames": c.band_frames,
               "nearest_bright_star_px": nearest_px(stars.x, stars.y, d.x, d.y)}
        if stamp_dir is not None and k < STAMP_CAP:
            rec["stamps"] = write_stamps(core, d, stamp_dir / name, f"{name}_c{c.rank:02d}")
        peaks.append(rec)
    meta = field_meta(name, ra, dec, pass_index, fd, core) | {
        "unit": "base", "peaks_ge7": peaks,
        "null_ge7": [round(s, 2) for s in sorted(null, reverse=True) if s >= THRESHOLD],
        "null_max": max(null, default=None), "n_real_ge5": len(core.detections),
        "n_null_ge5": len(null),
        "d_motion_au": motion_distance(core.geom, MIN_MOTION_PX),
        "min_motion_px": MIN_MOTION_PX, "n_bright_stars": int(np.size(stars.x)),
        "warnings": list(stars.warnings) + list(kwarn),
        "n_known_objects": len(knowns),
        "total_s": time.time() - t0, "cpu_s": time.process_time() - c0}
    log.info("%s base: %d peaks >= 7, null max %s", name, len(peaks), meta["null_max"])
    return _plain(meta)


def injection_unit(name: str, ra: float, dec: float, pass_index: int,
                   run: int) -> dict[str, Any]:
    """campaign.injection_unit, with its per-source arrays copied into the plain dict."""
    import io

    from pxs.movers.campaign import _plain
    from pxs.movers.campaign import injection_unit as campaign_injection

    data, meta = campaign_injection(name, ra, dec, pass_index, run)
    z = np.load(io.BytesIO(data))
    inj = {k: z[k].tolist() for k in ("inj_flux", "inj_rate", "inj_d", "inj_rec", "inj_pos",
                                      "inj_snr")}
    return _plain(meta | {"unit": f"run{run:02d}", "injections": inj,
                          "flux_unit": "mJy at 1 um"})
