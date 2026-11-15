"""Image stacks for a moving body, built with `pxs.spherex.stack.frame_layer` and `combine`.

Body-centred: each frame is resampled onto its own Grid centred on the body's ephemeris
position at that frame's time, so the body stays at the centre and stars trail.

Sky-fixed: a flipbook of short sub-stacks on one fixed grid. Within one pass Haumea and
Makemake move 56-188 px and Eris 9-32 px, so a literal first-half / second-half stack
would smear the body over tens of pixels. Instead frames are grouped into short windows
in which the body moves at most MAX_SMEAR_PX native pixels, and the windows that fit in
the field are shown one after another; the body steps across the field between them.

Units: degrees, arcsec, MJy/sr images, MJD.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pxs.grid import Grid, Stack
from pxs.spherex import config as spx_config
from pxs.spherex.stack import combine, frame_layer

from .phot import Measured

FOV_ARCSEC = 180.0
SIZE_PX = 90  # 2 arcsec per pixel, a third of a SPHEREx pixel
MAX_SMEAR_PX = 1.0  # body motion allowed inside one sky-fixed sub-stack, native pixels
TRACK_SHARE = 0.6  # share of the field the flipbook's track may span
EXTRA_HALF = math.ceil(TRACK_SHARE * FOV_ARCSEC / 2 / spx_config.PIXSCALE_ARCSEC)


def read_half(fov_arcsec: float = FOV_ARCSEC) -> int:
    """Stamp half-size (native px) covering a body-centred grid and an offset sky-fixed one."""
    return math.ceil(fov_arcsec * math.sqrt(2) / 2 / spx_config.PIXSCALE_ARCSEC) + 3 + EXTRA_HALF


def _stack(items: Sequence[Measured], grids: Sequence[Grid], band: str,
           window: tuple[float, float]) -> Stack:
    layers = [frame_layer(m.stamp, g) for m, g in zip(items, grids)]
    image = combine(np.array([la[0] for la in layers]), np.array([la[1] for la in layers]))
    flagged, usable = sum(la[2] for la in layers), sum(la[3] for la in layers)
    mjds = np.array([m.stamp.mjd for m in items])
    return Stack(image=image, mission="SPHEREx", band=band, wavelength_um=window,
                 mjd=float(mjds.mean()), date_span_days=float(np.ptp(mjds)),
                 n_exposures=len(items), native_pixscale_arcsec=spx_config.PIXSCALE_ARCSEC,
                 flag_fraction=flagged / usable if usable else 0.0)


def in_window(items: Sequence[Measured], window: tuple[float, float]) -> list[Measured]:
    lo, hi = window
    return [m for m in items if lo <= m.stamp.wave_um < hi]


def body_centred(items: Sequence[Measured], band: str, window: tuple[float, float],
                 fov: float = FOV_ARCSEC, size: int = SIZE_PX) -> Stack | None:
    """Stack of a pass's frames in `window`, each on a grid centred on the body."""
    use = in_window(items, window)
    if not use:
        return None
    grids = [Grid(m.visit.eph.ra, m.visit.eph.dec, fov, size) for m in use]
    return _stack(use, grids, band, window)


def _sep_arcsec(a: Measured, b: Measured) -> float:
    ea, eb = a.visit.eph, b.visit.eph
    dra = ((ea.ra - eb.ra + 180) % 360 - 180) * math.cos(math.radians(0.5 * (ea.dec + eb.dec)))
    return math.hypot(dra, ea.dec - eb.dec) * 3600.0


def short_windows(items: Sequence[Measured], max_smear_px: float = MAX_SMEAR_PX
                  ) -> list[list[Measured]]:
    """Consecutive frames grouped so the body moves at most max_smear_px within a group."""
    groups: list[list[Measured]] = []
    limit = max_smear_px * spx_config.PIXSCALE_ARCSEC
    for m in sorted(items, key=lambda m: m.stamp.mjd):
        if groups and _sep_arcsec(groups[-1][0], m) <= limit:
            groups[-1].append(m)
        else:
            groups.append([m])
    return groups


@dataclass(frozen=True)
class SkyFixed:
    """A flipbook of sub-stacks on one fixed grid, with the body's position in each."""

    grid: Grid
    stacks: tuple[Stack, ...]
    body_px: tuple[tuple[float, float], ...]  # edge-convention [x, y] on `grid`
    track_arcsec: float  # how far the body moves between the first and last sub-stack


def sky_fixed(items: Sequence[Measured], band: str, window: tuple[float, float],
              fov: float = FOV_ARCSEC, size: int = SIZE_PX) -> SkyFixed | None:
    """The run of short windows that fits in TRACK_SHARE of the field and holds most frames.

    None when the body moves less than 2 native pixels over the whole pass in this band
    (then a sky-fixed blink shows nothing a body-centred stack does not).
    """
    groups = short_windows(in_window(items, window))
    if len(groups) < 2 or _sep_arcsec(groups[0][0], groups[-1][-1]) < 2 * spx_config.PIXSCALE_ARCSEC:
        return None
    reach = TRACK_SHARE * fov
    best: list[list[Measured]] = []
    for i in range(len(groups)):
        run = [g for g in groups[i:] if _sep_arcsec(groups[i][0], g[-1]) <= reach]
        if sum(len(g) for g in run) > sum(len(g) for g in best):
            best = run
    if len(best) < 2:
        return None
    first, last = best[0][0].visit.eph, best[-1][-1].visit.eph
    dra = ((last.ra - first.ra + 180) % 360) - 180
    grid = Grid((first.ra + dra / 2) % 360, (first.dec + last.dec) / 2, fov, size)
    stacks = tuple(_stack(g, [grid] * len(g), band, window) for g in best)
    pos = []
    for g in best:
        x, y = grid.sky_to_px(np.mean([m.visit.eph.ra for m in g]),
                              np.mean([m.visit.eph.dec for m in g]))
        pos.append((float(x), float(y)))
    return SkyFixed(grid, stacks, tuple(pos), _sep_arcsec(best[0][0], best[-1][-1]))
