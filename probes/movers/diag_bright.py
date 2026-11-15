"""Probe: what are the excess S/N >= 7 peaks in the bright-star control fields?

Runs one campaign field's real and mirrored search (heavy: run it on Modal through
probes/movers/diag_bright_modal.py) and dumps, per detection down to S/N 5, its track,
per-frame psi/phi, the FLAGS bits under the track and the reference brightness there, plus
field maps (median image and reference, per-bit flag counts, the search S/N maps). The
analysis (catalogue distances, wavelength dependence, figures) is diag_bright_plots.py.
"""
from __future__ import annotations

import io
import logging

import numpy as np

from pxs.movers.candidates import track_xy
from pxs.movers.core import run_core
from pxs.movers.difference import reference_for
from pxs.movers.field import load_field
from pxs.movers.layers import grid_native_xy
from pxs.movers.search import track_sums

log = logging.getLogger(__name__)
N_BITS = 29


def grid_flags(s, grid) -> np.ndarray:
    """FLAGS of the native pixel nearest each grid pixel centre (0 off the stamp)."""
    x, y = grid_native_xy(s, grid)
    ix, iy = np.rint(x).astype(int) - s.x0, np.rint(y).astype(int) - s.y0
    h, w = s.flags.shape
    ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    out = np.zeros(ix.shape, np.int32)
    out[ok] = s.flags[iy[ok], ix[ok]]
    return out


def _dets(core, dets, sign, flags, ref):
    rows = {k: [] for k in ("x", "y", "snr", "snr_raw", "trial", "n_frames", "n_clipped",
                            "track", "psi", "phi", "flags", "ref")}
    n = len(core.cube)
    idx = np.arange(n)
    h = flags.shape[1]
    for d in dets:
        t = track_xy(core.trials, d, sign)
        psi, phi = track_sums(core.planes, sign * core.trials.offsets[d.trial], d.x, d.y)
        xs, ys = np.clip(t[0], 0, h - 1), np.clip(t[1], 0, h - 1)
        for k, v in (("x", d.x), ("y", d.y), ("snr", d.snr), ("snr_raw", d.snr_raw),
                     ("trial", d.trial), ("n_frames", d.n_frames),
                     ("n_clipped", d.n_clipped), ("track", t), ("psi", psi), ("phi", phi),
                     ("flags", flags[idx, ys, xs]), ("ref", ref[idx, ys, xs])):
            rows[k].append(v)
    return {k: np.array(v) for k, v in rows.items()}


def var_vs_image(refs) -> np.ndarray:
    """Per reference frame: (median variance, slope and correlation of variance against image
    over pixels > 5 sigma above the frame's median). A slope > 0 means VARIANCE carries the
    source's own photon noise, so per-pixel inverse-variance weights depend on the data."""
    rows = []
    for r in refs:
        im, va = r.image, r.variance
        ok = np.isfinite(im) & np.isfinite(va) & (va > 0)
        v = im[ok]
        med = np.median(v)
        sig = 1.4826 * np.median(np.abs(v - med))
        hot = ok & (im - med > 5 * sig)
        if hot.sum() < 20:
            rows.append((np.median(va[ok]), np.nan, np.nan))
            continue
        x, y = im[hot] - med, va[hot]
        rows.append((np.median(va[ok]), np.polyfit(x, y, 1)[0], np.corrcoef(x, y)[0, 1]))
    return np.array(rows, float)


def diagnose(ra: float, dec: float, pass_index: int) -> bytes:
    fd = load_field(ra, dec, 20.0, pass_index)
    core = run_core(fd.search, fd.refs, ra, dec, fd.grid.pixscale_arcsec)
    ref = np.stack([reference_for(s, fd.refs)[0] for s in fd.search]).astype(np.float32)
    flags = np.stack([grid_flags(s, fd.grid) for _, s in fd.search_stamps])
    counts = np.stack([((flags >> b) & 1).sum(0) for b in range(N_BITS)]).astype(np.uint8)
    img = np.nanmedian(np.stack([s.image for s in fd.search]), axis=0).astype(np.float32)
    out = {"img": img, "ref_med": np.nanmedian(ref, axis=0).astype(np.float32),
           "flag_counts": counts, "snr_map": core.maps.best_snr,
           "mjd": core.cube.mjd, "wave": core.cube.wave_um, "det": core.cube.detector,
           "template": core.cube.template, "noise_scale": core.planes.noise_scale,
           "dt": core.geom.dt, "masked": np.isnan(core.cube.diff).mean(0).astype(np.float32),
           "psi": core.planes.psi, "phi": core.planes.phi,
           "ref_var_vs_img": var_vs_image(fd.refs)}
    for tag, dets, sign in (("real", core.detections, 1), ("null", core.null_detections, -1)):
        for k, v in _dets(core, dets, sign, flags, ref).items():
            out[f"{tag}_{k}"] = v
    buf = io.BytesIO()
    np.savez_compressed(buf, **out)
    return buf.getvalue()
