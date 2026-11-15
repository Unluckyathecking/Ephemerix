"""The view manifest for a Solar System body (docs/api.md, schema 1) plus the
`solar_system` extension block proposed in the PR.

What fits schema 1: `frames` is a sky-fixed flipbook of one detected pass in the body's
best band (short sub-stacks; the body steps across the field), `predicted_px` is the
body's ephemeris position in each, `track` is the same positions with decimal years,
`spectra` are per-pass spectra (control-subtracted), `match` is null (brown-dwarf
templates do not apply), `features` shades the ice bands. Everything else goes in
`solar_system`. Units as in docs/api.md; reflectance is dimensionless.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pxs import render
from pxs.astrometry import decimal_year
from pxs.grid import Stack
from pxs.spectra import iso_date, pass_ids

from .bands import CONT_UM, WINDOWS, band_depths, reading
from .phot import BANDS
from .pipeline import BodyRun, PassResult, control_corrected_points
from .solar import NORM_WINDOW_UM, reflectance, thermal_cutoff_um
from .track import Track

SCHEMA = 1
SPHEREX_CREDIT = "SPHEREx DR1/QR3 spectral images, NASA/JPL-Caltech via NASA/IPAC IRSA"
CREDITS = (
    SPHEREX_CREDIT,
    "Ephemerides: NASA/JPL Horizons (ssd.jpl.nasa.gov), observer SPHEREx (-163182)",
    "Solar reference: CALSPEC sun_mod_001 (Bohlin, Gordon & Tremblay 2014, PASP 126, 711)",
)
NO_MATCH = ("The spectrum is not typed: the brown-dwarf templates do not apply to a Solar "
            "System body, which shines by reflected sunlight.")
METHOD = (
    "Forced ePSF photometry at the JPL Horizons position (seen from SPHEREx) in every "
    "exposure; errors scaled by the scatter at 8 empty positions per frame. Controls: the "
    "same photometry at 8 track positions in the body's other passes, when it is degrees "
    "away; the body flux is body minus control per detector band. Reflectance: flux "
    "divided by the CALSPEC solar model averaged over each channel, normalised over "
    f"{NORM_WINDOW_UM[0]:g}-{NORM_WINDOW_UM[1]:g} um. Band depth: 1 - (mean reflectance "
    f"in band / mean over {CONT_UM[0]:g}-{CONT_UM[1]:g} um).")


def _r(v: float, nd: int = 4) -> float | None:
    return round(float(v), nd) if v is not None and math.isfinite(v) else None


def _point(p: dict) -> dict:
    return {"wl_um": _r(p["wl_um"], 5), "bw_um": _r(p["bw_um"], 5), "flux": _r(p["flux"], 6),
            "err": _r(p["err"], 6), "detector": p["detector"], "flagged": bool(p["flagged"])}


def _spectrum(res: PassResult, sid: str) -> dict:
    pts = sorted(control_corrected_points(res.points, res.control), key=lambda p: p["wl_um"])
    mjds = [m.point.mjd for m in res.measured]
    return {"id": sid, "label": f"Pass of {iso_date(min(mjds))[:10]} (control subtracted)",
            "date_start": iso_date(min(mjds)), "date_end": iso_date(max(mjds)), "unit": "mJy",
            "points": [_point(p) for p in pts]}


def _ephem(res: PassResult) -> list[dict]:
    seen, out = set(), []
    for m in sorted(res.measured, key=lambda m: m.stamp.mjd):
        e = m.visit.eph
        if int(e.mjd) in seen:
            continue
        seen.add(int(e.mjd))
        out.append({"mjd": _r(e.mjd, 5), "ra": _r(e.ra, 6), "dec": _r(e.dec, 6),
                    "rate_arcsec_h": _r(e.rate_arcsec_h, 3), "vmag": _r(e.vmag, 2),
                    "r_au": _r(e.r_au, 3), "delta_au": _r(e.delta_au, 3),
                    "phase_deg": _r(e.phase_deg, 3), "elong_deg": _r(e.elong_deg, 2)})
    return out


def _pass_block(res: PassResult, sid: str) -> dict:
    c = res.control
    best = res.best
    return {
        "id": sid, "date_start": iso_date(res.pas.mjd_start), "date_end": iso_date(res.pas.mjd_end),
        "n_frames": len(res.pas.frames), "n_measured": len(res.measured),
        "bands": [b.to_dict() for b in res.corrected],
        "bands_before_control": [b.to_dict() for b in res.bands],
        "control": None if c is None else {"n_positions": c.n_positions, "n_frames": c.n_frames,
                                           "bands": [b.to_dict() for b in c.bands]},
        "best_band": best.band if best else None,
        "best_snr": _r(best.snr, 2) if best else None, "detected": res.detected,
        "outcome": res.outcome,
        "ephemeris": _ephem(res),
    }


def _write_stacks(stacks: Sequence[tuple[str, str, Stack]], root: Path, sub: str) -> list[str]:
    """Render (id, band, stack) with one stretch per band; returns relative image paths."""
    paths = []
    by_band: dict[str, list[Stack]] = {}
    for _, band, st in stacks:
        by_band.setdefault(band, []).append(st)
    stretch = {b: render.shared_stretch(v) for b, v in by_band.items()}
    for fid, band, st in stacks:
        rel = f"{sub}/{fid}.png"
        render.write_png(st, stretch[band], root / rel)
        paths.append(rel)
    return paths


def _frames(res: PassResult, sid: str, root: Path) -> tuple[list[dict], list[dict], dict]:
    sky = res.sky
    if sky is None:
        return [], [], {}
    items = [(f"{sid}-{res.sky_band}-{i:02d}", res.sky_band, st) for i, st in enumerate(sky.stacks)]
    paths = _write_stacks(items, root, "frames")
    frames, track = [], []
    for (fid, band, st), path, (x, y) in zip(items, paths, sky.body_px):
        inside = 0 <= x <= sky.grid.size_px and 0 <= y <= sky.grid.size_px
        px = [_r(x, 3), _r(y, 3)] if inside else None
        frames.append({
            "id": fid, "mission": "SPHEREx", "band": band,
            "wavelength_um": [_r(w, 4) for w in st.wavelength_um], "date": iso_date(st.mjd),
            "mjd": _r(st.mjd, 5), "date_span_days": _r(st.date_span_days, 3),
            "n_exposures": st.n_exposures, "native_pixscale_arcsec": _r(st.native_pixscale_arcsec, 3),
            "image": path, "predicted_px": px, "centroid_px": None, "centroid_err_arcsec": None,
            "flag_fraction": _r(min(max(st.flag_fraction, 0.0), 1.0), 4), "warnings": []})
        if px:
            track.append({"year": _r(float(decimal_year(st.mjd)), 5), "px": px})
    g = sky.grid
    return frames, track, {"center": {"ra": round(g.center_ra, 7), "dec": round(g.center_dec, 7)},
                           "fov_arcsec": g.fov_arcsec, "size_px": g.size_px}


def _body_frames(results: Sequence[tuple[PassResult, str]], root: Path) -> dict:
    items = [(f"{sid}-{band}-body", band, st) for res, sid in results for band, st in res.body_stacks]
    paths = _write_stacks(items, root, "body")
    frames = [{"id": fid, "band": band, "wavelength_um": [_r(w, 4) for w in st.wavelength_um],
               "date": iso_date(st.mjd), "mjd": _r(st.mjd, 5),
               "date_span_days": _r(st.date_span_days, 3), "n_exposures": st.n_exposures,
               "image": path} for (fid, band, st), path in zip(items, paths)]
    fov = next((st.image.shape[0] for _, _, st in items), 0)
    return {"note": "Each exposure resampled on a grid centred on the body at its own time: "
                    "the body stays at the centre and background stars trail.",
            "size_px": fov, "frames": frames}


def _refl_block(points: list[dict], sid: str, published: str, r_au: float) -> dict:
    """Reflectance and band depths; points where thermal emission may matter are dropped."""
    cut = thermal_cutoff_um(r_au) if math.isfinite(r_au) else None
    refl, norm = reflectance([p for p in points if cut is None or p["wl_um"] < cut])
    depths = band_depths(refl)
    return {"spectrum_id": sid, "norm_window_um": list(NORM_WINDOW_UM),
            "thermal_cutoff_um": cut, "r_au": _r(r_au, 3),
            "points": [{"wl_um": _r(p.wl_um, 5), "bw_um": _r(p.bw_um, 5), "refl": _r(p.refl, 4),
                        "err": _r(p.err, 4)} for p in sorted(refl, key=lambda p: p.wl_um)],
            "band_depths": [d.to_dict() for d in depths],
            "reading": reading(depths, published) if norm else "No continuum flux to normalise."}


def _r_au(res: PassResult) -> float:
    """Median heliocentric distance (au) over the pass."""
    vals = sorted(m.visit.eph.r_au for m in res.measured if math.isfinite(m.visit.eph.r_au))
    return vals[len(vals) // 2] if vals else math.nan


def _search(track: Track | None) -> dict | None:
    """How the exposures were found; None when the ephemeris could not be had."""
    if track is None:
        return None
    return {"index_days": track.n_index_days, "sia_cones": track.n_cones,
            "failed_sia_cones": track.failed_cones, "candidate_frames": len(track.visits)}


def build(run: BodyRun, root: Path) -> dict:
    """The manifest dict; images are written under `root`. Caller validates and writes it."""
    body = run.body
    passes = sorted(run.passes, key=lambda r: r.pas.mjd_start)
    ids = pass_ids([r.points for r in passes]) if passes else []
    spectra = [_spectrum(r, sid) for r, sid in zip(passes, ids)]
    det = [(r, sid) for r, sid in zip(passes, ids) if r.detected]
    show = max(det, key=lambda t: t[0].best.snr, default=None)  # type: ignore[union-attr]
    frames, track, grid = _frames(*show, root) if show else ([], [], {})
    refl = [_refl_block(control_corrected_points(r.points, r.control), sid, body.composition,
                        _r_au(r)) for r, sid in det]
    if len(det) > 1:
        allp = [p for r, _ in det for p in control_corrected_points(r.points, r.control)]
        refl.append(_refl_block(allp, "all-detected", body.composition,
                                min(_r_au(r) for r, _ in det)))
    warnings = list(dict.fromkeys([*run.warnings, NO_MATCH]))
    if not det and run.track is not None:
        warnings.append("The body is not detected in any SPHEREx pass (a detection needs "
                        "S/N 5 in two detector bands).")
    mid = show[0].best and show[0].measured[len(show[0].measured) // 2].visit.eph if show else None
    return {
        "schema": SCHEMA, "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": {"name": body.name, "slug": body.slug, "ra": _r(mid.ra, 7) if mid else None,
                   "dec": _r(mid.dec, 7) if mid else None, "epoch": None, "pmra_masyr": None,
                   "pmdec_masyr": None, "blurb": body.blurb},
        **(grid or {"center": None, "fov_arcsec": None, "size_px": None}),
        "frames": frames, "track": track, "spectra": spectra, "match": None,
        "features": [{"label": k, "wl_um": list(v)} for k, v in WINDOWS.items()],
        "overlays": {}, "vetting": None, "measured_motion": None, "degraded": bool(run.warnings),
        "warnings": warnings, "credits": list(CREDITS),
        "solar_system": {
            "designation": body.designation, "type": body.kind,
            "horizons_command": body.horizons, "composition": body.composition,
            "composition_ref": body.composition_ref, "shown_pass": show[1] if show else None,
            "passes": [_pass_block(r, sid) for r, sid in zip(passes, ids)],
            "skipped_passes": [{"date_start": iso_date(p.mjd_start), "n_candidate_frames": n,
                                "reason": "fewer than 6 exposures contain the body"}
                               for p, n in run.skipped_passes],
            "reflectance": refl, "body_frames": _body_frames(det, root),
            "sky_track_arcsec": _r(show[0].sky.track_arcsec, 1) if show and show[0].sky else None,
            "detector_bands": {k: list(v) for k, v in BANDS.items()},
            "frame_search": _search(run.track), "timings_s": dict(run.timings),
            "method": METHOD,
        },
    }
