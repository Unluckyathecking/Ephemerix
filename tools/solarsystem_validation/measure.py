"""Per-pass measurements for the body-recovery campaign, as plain JSON-ready dicts.

Pre-registered rules:
- detected: the pipeline's own rule (pxs.solarsystem.pipeline.pass_outcome). Campaign v1
  (Nov 2026) ran under the earlier rule, best control-corrected band S/N >= 5, which is
  `candidate` here; analyse.py re-decides v1 records from their band S/N values.
- recovered: detected, and the centroid of the body-centred stack in the best band lies
  within POSITION_GATE_ARCSEC (2 SPHEREx pixels) of the predicted position.
- negative controls: the same frames and pipeline on the track shifted by OFFSETS; a
  control pass is a false detection when it would count as recovered.

Units: arcsec, degrees, mJy (bands as uJy in the records), V magnitude.
Written with Claude Code.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import requests

from pxs.solarsystem.horizons import EphemPoint, HorizonsError
from pxs.solarsystem.phot import BANDS
from pxs.solarsystem.pipeline import DETECTION_SNR, PassResult
from pxs.solarsystem.stacks import FOV_ARCSEC, SIZE_PX, body_centred
from pxs.solarsystem.track import Visit
from pxs.spherex import config as spx_config
from pxs.spherex.net import TransientError

POSITION_GATE_ARCSEC = 2 * spx_config.PIXSCALE_ARCSEC
OFFSETS: dict[str, tuple[float, float]] = {"off_ra": (180.0, 0.0), "off_dec": (0.0, -180.0)}
SEARCH_ARCSEC = 12.0  # peak search radius around the predicted position
WINDOW_ARCSEC = 8.0  # centroid window around the peak
SKY_INNER_ARCSEC, SKY_OUTER_ARCSEC = 30.0, 60.0
CENTROID_ITERATIONS = 5


def shift(e: EphemPoint, east_arcsec: float, north_arcsec: float) -> EphemPoint:
    """The ephemeris point moved on the sky by (east, north) arcsec; everything else kept."""
    cosd = max(math.cos(math.radians(e.dec)), 1e-6)
    return replace(e, ra=(e.ra + east_arcsec / 3600.0 / cosd) % 360.0,
                   dec=e.dec + north_arcsec / 3600.0)


def offset_visits(visits: Sequence[Visit], east_arcsec: float, north_arcsec: float
                  ) -> list[Visit]:
    """The same frames with the predicted position shifted (a track with no body on it)."""
    return [Visit(v.frame, shift(v.eph, east_arcsec, north_arcsec)) for v in visits]


def centroid_offset(image: np.ndarray, pix_arcsec: float = FOV_ARCSEC / SIZE_PX
                    ) -> tuple[float, float] | None:
    """(east, north) arcsec of the source near the centre of a body-centred stack.

    Sky: median of an annulus. Peak: brightest pixel within SEARCH_ARCSEC of the centre.
    Centroid: sky-subtracted, positive-clipped first moment within WINDOW_ARCSEC, the
    window started on the peak and re-centred on each new centroid. None when there is no positive signal. Precision is limited by the 2 arcsec grid
    and the undersampled 6.15 arcsec SPHEREx pixel; this is a position gate, not astrometry.
    On a Grid +x is west and +y is south (both cdelt negative).
    """
    img = np.asarray(image, dtype=float)
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny, 0:nx] + 0.5
    cx, cy = nx / 2.0, ny / 2.0
    r = np.hypot(xx - cx, yy - cy) * pix_arcsec
    ann = img[(r >= SKY_INNER_ARCSEC) & (r <= SKY_OUTER_ARCSEC) & np.isfinite(img)]
    if ann.size == 0:
        return None
    d = img - float(np.median(ann))
    near = (r <= SEARCH_ARCSEC) & np.isfinite(d)
    if not near.any() or np.nanmax(np.where(near, d, np.nan)) <= 0:
        return None
    k = int(np.nanargmax(np.where(near, d, -np.inf)))
    x0, y0 = float(xx.flat[k]), float(yy.flat[k])
    for _ in range(CENTROID_ITERATIONS):  # re-centre the window on the last centroid
        win = (np.hypot(xx - x0, yy - y0) * pix_arcsec <= WINDOW_ARCSEC) & np.isfinite(d)
        w = np.clip(np.where(win, d, 0.0), 0.0, None)
        if w.sum() <= 0:
            return None
        x0, y0 = float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())
    return -(x0 - cx) * pix_arcsec, -(y0 - cy) * pix_arcsec


def galactic_b(ra: float, dec: float) -> float:
    from astropy.coordinates import SkyCoord

    return float(SkyCoord(ra, dec, unit="deg").galactic.b.deg)


def plain(obj):
    """JSON-ready copy: numpy scalars to Python, tuples to lists, NaN/inf to None."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if obj is None or isinstance(obj, str):
        return obj
    raise TypeError(f"not JSON-ready: {type(obj).__name__}")


def classify_error(e: BaseException) -> str:
    """Failure kind for the report: horizons, network, timeout or bug."""
    if isinstance(e, HorizonsError):
        return "horizons"
    if isinstance(e, TimeoutError) or type(e).__name__ == "FunctionTimeoutError":
        return "timeout"
    if isinstance(e, (TransientError, requests.RequestException)):
        return "network"
    return "bug"


def _median(xs: Sequence[float]) -> float:
    ok = [x for x in xs if math.isfinite(x)]
    return statistics.median(ok) if ok else math.nan


def _recentre(res: PassResult) -> dict | None:
    """PSF-fit pass offset (pxs.spherex.recentre) with error scale 1; None if it fails."""
    from pxs.spherex.recentre import fit_offset

    try:
        return fit_offset([m.stamp for m in res.measured]).as_dict()
    except Exception as e:  # noqa: BLE001 - an optional cross-check must not lose the pass
        return {"error": f"{type(e).__name__}: {e}"}


def pass_record(res: PassResult) -> dict:
    """Everything the analysis needs from one analysed pass (no stacks kept)."""
    ephs = [m.visit.eph for m in res.measured]
    pts = res.points
    best = res.best
    centroid = recentre = None
    if res.candidate and best is not None:  # also for marginal passes, to study them
        st = body_centred(res.measured, best.band, BANDS[best.band])
        c = centroid_offset(st.image) if st is not None else None
        if c is not None:
            centroid = {"east": c[0], "north": c[1], "total": math.hypot(*c)}
        recentre = _recentre(res)
    mid = ephs[len(ephs) // 2] if ephs else None
    return plain({
        "date_start": res.pas.frames[0].mjd, "date_end": res.pas.frames[-1].mjd,
        "n_frames": len(res.pas.frames), "n_measured": len(res.measured),
        "n_usable": sum(1 for p in pts if not p.flagged),
        "n_saturated": sum(1 for p in pts if p.reason == "saturated"),
        "n_failed_reads": res.n_failed,
        "vmag": _median([e.vmag for e in ephs]), "r_au": _median([e.r_au for e in ephs]),
        "delta_au": _median([e.delta_au for e in ephs]),
        "rate_arcsec_h": _median([e.rate_arcsec_h for e in ephs]),
        "ra": mid.ra if mid else None, "dec": mid.dec if mid else None,
        "gal_b": galactic_b(mid.ra, mid.dec) if mid else None,
        "best_band": best.band if best else None, "best_snr": best.snr if best else None,
        "best_flux_ujy": best.flux_mjy * 1000 if best else None,
        "detected": res.detected, "candidate": res.candidate, "outcome": res.outcome,
        "snr_threshold": DETECTION_SNR,
        "centroid": centroid, "recentre": recentre,
        "recovered": bool(res.detected and centroid is not None
                          and centroid["total"] <= POSITION_GATE_ARCSEC),
        "bands": [b.to_dict() for b in res.corrected],
        "control_bands": [b.to_dict() for b in res.control.bands] if res.control else [],
    })
