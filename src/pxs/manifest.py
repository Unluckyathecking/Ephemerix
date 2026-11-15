"""Assemble the view manifest (docs/api.md, schema 1) and validate it before it is written.

Units follow docs/api.md: degrees, arcsec where named, mas/yr, MJD and ISO 8601 UTC,
edge-convention pixel coordinates [x, y] with [0, 0] at the top-left corner.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pxs.astrometry import fit_motion, px_to_sky
from pxs.centroid import Centroid
from pxs.fieldcheck import GLARE_FLAG_FRACTION
from pxs.fitblend import is_blended
from pxs.grid import Grid, Stack
from pxs.sources import SPHEREX_WINDOWS, WISE_BANDS, Target
from pxs.spectra import iso_date

SCHEMA = 1
MISSIONS = ("WISE", "SPHEREx")
BANDS = (*WISE_BANDS, *SPHEREX_WINDOWS)
CONFIDENCE = ("high", "medium", "low")
CREDITS = {
    "WISE": "WISE and NEOWISE single-exposure images, NASA/JPL-Caltech/UCLA via NASA/IPAC IRSA",
    "SPHEREx": "SPHEREx DR1/QR3 spectral images, NASA/JPL-Caltech via NASA/IPAC IRSA",
    "gaia": "Gaia DR3, ESA/Gaia/DPAC (Gaia Collaboration 2023)",
    "catwise": "CatWISE2020 (Marocco et al. 2021) via NASA/IPAC IRSA",
    "match": "SPIFF spectral templates (Gagné et al., arXiv:2604.22012)",
}


class ManifestError(ValueError):
    """A manifest breaks the contract. The message lists every problem found."""


def _r(v: float, nd: int = 3) -> float:
    return round(float(v), nd)


def frame_entry(fid: str, band: str, stack: Stack, image: str,
                predicted: tuple[float, float] | None, centroid: Centroid | None,
                notes: Sequence[str] = ()) -> dict:
    """One `frames` item. `image` is relative to the manifest; `notes` are extra warnings."""
    return {
        "id": fid, "mission": stack.mission, "band": band,
        "wavelength_um": [_r(w, 4) for w in stack.wavelength_um],
        "date": iso_date(stack.mjd), "mjd": _r(stack.mjd, 5),
        "date_span_days": _r(stack.date_span_days), "n_exposures": int(stack.n_exposures),
        "native_pixscale_arcsec": _r(stack.native_pixscale_arcsec),
        "image": image,
        "predicted_px": None if predicted is None else [_r(predicted[0]), _r(predicted[1])],
        "centroid_px": None if centroid is None else [_r(centroid.x), _r(centroid.y)],
        "centroid_err_arcsec": None if centroid is None else _r(centroid.err_arcsec),
        "flag_fraction": _r(min(max(stack.flag_fraction, 0.0), 1.0), 4),
        "warnings": [*stack.warnings, *(centroid.warnings if centroid else ()), *notes],
    }


MOTION_BANDS = {"WISE": "W2", "SPHEREx": "spx-b6"}  # same object, similar wavelength


def motion_frames(frames: Sequence[dict]) -> list[dict]:
    """Detected frames of ONE band per mission, fitted as one series: W2 and spx-b6 when they
    have detections, else the band with most detections (ties: longer wavelength). So the
    W1 and W2 centroids of one visit are never two independent points. Frames flagged as
    blended with a catalogued neighbour (`fitblend`) are left out, and so are frames with at
    least GLARE_FLAG_FRACTION of their pixels flagged (mostly glare or gaps)."""
    chosen = []
    for mission in MISSIONS:
        det = [f for f in frames if f["mission"] == mission and f["centroid_px"] is not None
               and not is_blended(f) and f.get("flag_fraction", 0.0) < GLARE_FLAG_FRACTION]
        if not det:
            continue
        counts = Counter(f["band"] for f in det)
        wl = {f["band"]: f["wavelength_um"][1] for f in det}
        band = MOTION_BANDS[mission]
        if band not in counts:
            band = max(counts, key=lambda b: (counts[b], wl[b]))
        chosen += [f for f in det if f["band"] == band]
    return chosen


def measured_motion(frames: Sequence[dict], grid: Grid,
                    parallax_mas: float | None = None) -> dict | None:
    """Manifest `measured_motion` from the centroids of `motion_frames`, with the parallax
    fixed at `parallax_mas` when known (else fitted when there are enough epochs)."""
    use = motion_frames(frames)
    if len(use) < 2:
        return None
    xs = [f["centroid_px"][0] for f in use]
    ys = [f["centroid_px"][1] for f in use]
    ra, dec = px_to_sky(xs, ys, grid.center_ra, grid.center_dec, grid.fov_arcsec, grid.size_px)
    return fit_motion([f["mjd"] for f in use], ra, dec, [f["centroid_err_arcsec"] for f in use],
                      parallax_mas=parallax_mas)


def target_block(t: Target) -> dict:
    return {"name": t.name, "slug": t.slug, "ra": t.ra, "dec": t.dec, "epoch": t.epoch,
            "pmra_masyr": t.pmra_masyr, "pmdec_masyr": t.pmdec_masyr, "blurb": t.blurb}


def credits(frames: Sequence[dict], overlays: dict, match: dict | None) -> list[str]:
    used = {f["mission"] for f in frames} | {k for k, v in overlays.items() if v}
    if match:
        used.add("match")
    return [text for key, text in CREDITS.items() if key in used]


def assemble(*, target: Target, grid: Grid, frames: list[dict], track: list[dict],
             spectra: list[dict], match: dict | None, features: list[dict], overlays: dict,
             warnings: Sequence[str], vetting: dict | None = None,
             degraded: bool = False, parallax_mas: float | None = None) -> dict:
    """The full manifest dict. Frames are sorted by date."""
    frames = sorted(frames, key=lambda f: (f["mjd"], f["id"]))
    return {
        "schema": SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target_block(target),
        "center": {"ra": round(grid.center_ra, 7), "dec": round(grid.center_dec, 7)},
        "fov_arcsec": grid.fov_arcsec, "size_px": grid.size_px,
        "frames": frames, "track": track, "spectra": spectra, "match": match,
        "features": features if spectra else [], "overlays": overlays,
        "measured_motion": measured_motion(frames, grid, parallax_mas),
        "vetting": vetting,
        "degraded": bool(degraded),  # a source or catalogue fetch failed; see warnings
        "warnings": list(dict.fromkeys(warnings)),
        "credits": credits(frames, overlays, match),
    }


# --- validation ---------------------------------------------------------------------------

def _num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _opt(v) -> bool:
    return v is None or _num(v)


def _str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _px(v, size: int, nullable: bool = True) -> bool:
    if v is None:
        return nullable
    return (isinstance(v, list) and len(v) == 2 and all(_num(c) for c in v)
            and all(0.0 <= c <= size for c in v))


def _check_frame(f: dict, size: int, root: Path | None, bad: list[str]) -> None:
    w = f"frame {f.get('id')!r}"
    req = {"id": _str, "date": _str, "image": _str, "mjd": _num, "warnings": lambda v:
           isinstance(v, list) and all(_str(s) for s in v)}
    bad += [f"{w}: bad or missing '{k}'" for k, ok in req.items() if not ok(f.get(k))]
    if f.get("mission") not in MISSIONS:
        bad.append(f"{w}: mission must be one of {MISSIONS}")
    if f.get("band") not in BANDS:
        bad.append(f"{w}: band must be one of {BANDS}")
    wl = f.get("wavelength_um")
    if not (isinstance(wl, list) and len(wl) == 2 and all(_num(x) for x in wl) and wl[0] < wl[1]):
        bad.append(f"{w}: wavelength_um must be [lo, hi] with lo < hi")
    for k in ("date_span_days", "n_exposures", "native_pixscale_arcsec"):
        if not (_num(f.get(k)) and f[k] >= 0):
            bad.append(f"{w}: '{k}' must be a number >= 0")
    if not (_num(f.get("flag_fraction")) and 0.0 <= f["flag_fraction"] <= 1.0):
        bad.append(f"{w}: flag_fraction must be in [0, 1]")
    for k in ("predicted_px", "centroid_px"):
        if not _px(f.get(k), size):
            bad.append(f"{w}: {k} must be [x, y] inside the image, or null")
    err = f.get("centroid_err_arcsec")
    if (f.get("centroid_px") is None) != (err is None) or not (err is None or _num(err) and err > 0):
        bad.append(f"{w}: centroid_err_arcsec must be > 0 with a centroid and null without")
    if root is not None and _str(f.get("image")) and not (root / f["image"]).is_file():
        bad.append(f"{w}: image file {f['image']} does not exist")


def _check_spectra(spectra, bad: list[str]) -> set[str]:
    ids = set()
    for s in spectra if isinstance(spectra, list) else []:
        w = f"spectrum {s.get('id')!r}"
        if not all(_str(s.get(k)) for k in ("id", "label", "date_start", "date_end")):
            bad.append(f"{w}: needs id, label, date_start and date_end")
        if s.get("unit") != "mJy":
            bad.append(f"{w}: unit must be 'mJy'")
        ids.add(s.get("id"))
        for p in s.get("points", []):
            ok = (_num(p.get("wl_um")) and p["wl_um"] > 0 and _opt(p.get("bw_um"))
                  and _opt(p.get("flux")) and _opt(p.get("err"))
                  and isinstance(p.get("flagged"), bool)
                  and (p.get("flagged") or (p.get("flux") is not None and p.get("err") is not None)))
            if not ok:
                bad.append(f"{w}: bad point {p}")
                break
    return ids


def _check_top(m: dict, bad: list[str]) -> None:
    if m.get("schema") != SCHEMA:
        bad.append(f"schema must be {SCHEMA}")
    c = m.get("center") or {}
    if not (_num(c.get("ra")) and _num(c.get("dec")) and -90 <= c["dec"] <= 90):
        bad.append("center must have finite ra and dec")
    if not (_num(m.get("fov_arcsec")) and m["fov_arcsec"] > 0):
        bad.append("fov_arcsec must be > 0")
    if not (isinstance(m.get("size_px"), int) and m["size_px"] > 0):
        bad.append("size_px must be a positive integer")
    t = m.get("target") or {}
    if not (_num(t.get("ra")) and _num(t.get("dec")) and _opt(t.get("epoch"))
            and _opt(t.get("pmra_masyr")) and _opt(t.get("pmdec_masyr"))):
        bad.append("target needs finite ra, dec and numeric-or-null epoch and proper motion")
    for k in ("warnings", "credits"):
        if not (isinstance(m.get(k), list) and all(_str(s) for s in m[k])):
            bad.append(f"{k} must be a list of non-empty strings")


MOVER_LABELS = ("target", "gaia", "catwise", "candidate")


def _check_field_movers(fm, size: int, bad: list[str]) -> None:
    """The optional `field_movers` block (docs/api.md); absent in older manifests."""
    if fm is None:
        return
    movers = fm.get("movers") if isinstance(fm, dict) else None
    if not isinstance(fm, dict) or fm.get("status") not in ("searched", "not_searched") \
            or not _str(fm.get("sentence")) or not isinstance(movers, list):
        bad.append("field_movers needs a status, a sentence and a movers list")
        return
    if fm["status"] == "not_searched" and (movers or not _str(fm.get("reason"))):
        bad.append("field_movers not searched needs a reason and no movers")
    for mv in movers:
        ok = (mv.get("label") in MOVER_LABELS and _px(mv.get("px"), size, False)
              and all(_num(mv.get(k)) for k in ("ra", "dec", "epoch", "pmra_masyr", "pmdec_masyr",
                                                "err_masyr", "significance"))
              and isinstance(mv.get("epochs"), list) and all(_str(e) for e in mv["epochs"]))
        if not ok:
            bad.append(f"field_movers: bad mover {mv}")


def validate(m: dict, root: Path | None = None) -> None:
    """Raise ManifestError listing every way `m` breaks docs/api.md. With `root`, image paths
    must exist relative to it. The manifest must also serialise as strict JSON (no NaN)."""
    bad: list[str] = []
    try:
        json.dumps(m, allow_nan=False)
    except (TypeError, ValueError) as exc:
        bad.append(f"not strict JSON: {exc}")
    _check_top(m, bad)
    size = m.get("size_px") if isinstance(m.get("size_px"), int) else 0
    frames = m.get("frames") if isinstance(m.get("frames"), list) else []
    if not frames:
        bad.append("frames must be a non-empty list")
    for f in frames:
        _check_frame(f, size, root, bad)
    ids = [f.get("id") for f in frames]
    if len(set(ids)) != len(ids):
        bad.append("frame ids must be unique")
    if [f.get("mjd") for f in frames] != sorted(f.get("mjd") or 0 for f in frames):
        bad.append("frames must be sorted by date")
    if not all(_num(p.get("year")) and _px(p.get("px"), size, False) for p in m.get("track", [])):
        bad.append("track points need a year and px inside the image")
    spec_ids = _check_spectra(m.get("spectra"), bad)
    match = m.get("match")
    if match is not None and (match.get("spectrum_id") not in spec_ids
                              or match.get("confidence") not in CONFIDENCE
                              or not _str((match.get("best") or {}).get("type"))):
        bad.append("match needs a spectrum_id from spectra, a best type and a valid confidence")
    ov = m.get("overlays") or {}
    for k in ("gaia", "catwise"):
        if not all(_num(s.get("ra")) and _num(s.get("dec")) for s in ov.get(k, [])):
            bad.append(f"overlays.{k} sources need finite ra and dec")
    mm = m.get("measured_motion")
    if mm is not None and not all(_num(mm.get(k)) for k in ("pmra_masyr", "pmdec_masyr")):
        bad.append("measured_motion needs numeric pmra_masyr and pmdec_masyr")
    _check_field_movers(m.get("field_movers"), size, bad)
    if bad:
        raise ManifestError("manifest is invalid:\n  - " + "\n  - ".join(bad))
