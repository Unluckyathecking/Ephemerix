"""Flag frames where a catalogued source of similar brightness sits inside the centroid fit.

The centroid (`centroid._fit`) fits ONE Gaussian to the pixels in a box of half-width
`centroid.fit_radius_arcsec` (11" in W2). Light of a second source in that box pulls the
fitted position towards it: WISE 1541-2250 in 2010-2016, with CatWISE J154151.69-225018.6
(W2 14.9, the target 14.2) 7" north, was measured up to 2" north of its track, and that bent
the fitted proper motion. A frame is BLENDED when a CatWISE source, at the frame epoch, lies
inside the box around the target's catalogue track and is no more than BRIGHTNESS_MAG
fainter than the target in the matching WISE band (W1 below 4 um, W2 above). Such frames
keep their centroid on the page but are left out of the motion fit (`manifest.motion_frames`).

A frame whose centroid was fitted together with its neighbour (`centroid.JOINT`: WISE frames,
neighbour at least 1.2 PSF widths away and at most 1.25 times as bright, `pairfit`) is not
flagged for that neighbour: its light is in the model. A brighter catalogued neighbour in
the box still flags it. `neighbours_px` gives the centroid the catalogued sources
to model, by the same brightness rule.

Known limit: closer or much brighter neighbours, and all SPHEREx frames, are still only
flagged. Widening the flag's reach by one FWHM (18" in W2) was tried and left out too much:
it removed every WISE epoch of WISE 1541-2250 and all but two of CWISE 1055+5443.

Pieces of the target itself in CatWISE are not neighbours (`blend.is_catwise_piece`).
Positions in degrees, motions in mas/yr, epochs in decimal years.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from types import SimpleNamespace

from pxs.astrometry import decimal_year
from pxs.blend import _at, _target_at, is_catwise_piece, separation_arcsec
from pxs.centroid import JOINT, fit_radius_arcsec, psf_fwhm_arcsec
from pxs.grid import Grid, Stack
from pxs.pairfit import MAX_FLUX_RATIO
from pxs.target import Target

BRIGHTNESS_MAG = 2.0  # a neighbour within 2 mag (flux ratio >= 0.16) can move the fit
W1_TOP_UM = 4.0  # frames whose window ends below this are compared in W1
BLENDED = "blended: a catalogued source"
JOINT_BRIGHTER_MAG = 2.5 * math.log10(MAX_FLUX_RATIO)  # 0.24 mag brighter than the target


def _mag_key(frame: dict) -> str:
    return "w1_mag" if frame["wavelength_um"][1] <= W1_TOP_UM else "w2_mag"


def _src_at(src: dict, year: float) -> tuple[float, float]:
    return _at(src["ra"], src["dec"], src["epoch"], src.get("pmra_masyr"),
               src.get("pmdec_masyr"), year)


def _neighbour(frame: dict, t: Target, catwise: Sequence[dict],
               pixscale_arcsec: float) -> tuple[float, float] | None:
    """(magnitude, separation arcsec) of the nearest qualifying neighbour, or None."""
    key = _mag_key(frame)
    mine = getattr(t, key)
    if mine is None:
        return None
    year = float(decimal_year(frame["mjd"]))
    radius = fit_radius_arcsec(psf_fwhm_arcsec(SimpleNamespace(**frame)), pixscale_arcsec)
    here = _target_at(t, year)
    # In a frame fitted together with its neighbour only a neighbour brighter than that fit
    # is checked for still counts.
    faintest = mine - JOINT_BRIGHTER_MAG if jointly_fitted(frame) else mine + BRIGHTNESS_MAG
    found = [(separation_arcsec(*here, *_src_at(s, year)), s[key]) for s in catwise
             if s.get(key) is not None and s[key] <= faintest
             and not is_catwise_piece(t, s)]
    near = [(sep, mag) for sep, mag in found if sep <= radius]
    return (min(near)[1], min(near)[0]) if near else None


def neighbours_px(t: Target, catwise: Sequence[dict], stack: Stack,
                  grid: Grid) -> list[tuple[float, float]]:
    """Grid pixel positions, at the stack's epoch, of the CatWISE sources the centroid may
    fit together with the target: bright enough to move its fit (the rule of `_neighbour`,
    without its distance limit) and not brighter than the joint fit is checked for."""
    key = _mag_key({"wavelength_um": stack.wavelength_um})
    mine = getattr(t, key)
    if mine is None:
        return []
    year = float(decimal_year(stack.mjd))
    sky = [_src_at(s, year) for s in catwise if s.get(key) is not None
           and mine - JOINT_BRIGHTER_MAG <= s[key] <= mine + BRIGHTNESS_MAG
           and not is_catwise_piece(t, s)]
    if not sky:
        return []
    x, y = grid.sky_to_px([ra for ra, _ in sky], [dec for _, dec in sky])
    return [(float(a), float(b)) for a, b in zip(x, y)]


def jointly_fitted(frame: dict) -> bool:
    return any(w.startswith(JOINT) for w in frame.get("warnings", ()))


def _note(frame: dict, mag: float, sep: float) -> str:
    band = "W1" if _mag_key(frame) == "w1_mag" else "W2"
    return (f"{BLENDED} ({band} {mag:.1f}) lies {sep:.1f} arcsec from the target, inside the "
            "area its position is fitted over, so this epoch is left out of the motion fit")


def flag(frames: Sequence[dict], t: Target, catwise: Sequence[dict],
         pixscale_arcsec: float) -> list[dict]:
    """The frames, with a BLENDED warning added where it applies (new dicts; inputs kept).
    Only frames with a centroid are flagged: an undetected frame has no position to bias.
    A frame fitted together with its neighbour is flagged only for a brighter one."""
    out = []
    for f in frames:
        hit = None if f.get("centroid_px") is None else _neighbour(f, t, catwise,
                                                                    pixscale_arcsec)
        out.append(f if hit is None else {**f, "warnings": [*f["warnings"], _note(f, *hit)]})
    return out


def is_blended(frame: dict) -> bool:
    return any(w.startswith(BLENDED) for w in frame.get("warnings", ()))


def n_blended(frames: Sequence[dict]) -> int:
    return sum(is_blended(f) for f in frames)
