"""Synthetic movers added to the real native stamps before resampling and differencing.

Each source is drawn with the frame's own ePSF at its predicted native position, so
resampling, PSF mismatch, flags, masks and integer-shift losses all reach the measured
completeness. Fluxes follow a spectral template (reflected sunlight, or flat F_nu for the
thermal mode), scaled to the source's flux at the template reference wavelength.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from pxs.grid import Grid
from pxs.spherex import config
from pxs.spherex.photometry import psf_model
from pxs.spherex.read import Stamp

from .geometry import AU_PER_DAY_CIRC_1AU, RAD_PER_ARCSEC, SPEED_FACTOR, PassGeometry

Template = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class Synthetic:
    """One injected mover: start (mid-pass) grid pixel (x, y), distance d (au), linear rate
    (vx, vy) px/day, flux (mJy at the template reference wavelength)."""

    x: float
    y: float
    d_au: float
    vx: float
    vy: float
    flux_mjy: float


def position_px(src: Synthetic, geom: PassGeometry, mjd: float) -> tuple[float, float]:
    """Grid pixel (index coordinates) of a synthetic mover at an MJD."""
    dt = mjd - geom.t0
    i = int(np.argmin(np.abs(geom.dt - dt)))
    # Curvature is tabulated at the frame times; the nearest frame is the frame itself.
    cx, cy = geom.curve_px[:, i] / src.d_au
    return src.x + src.vx * dt + cx, src.y + src.vy * dt + cy


def injector(sources: list[Synthetic], geom: PassGeometry, grid: Grid,
             template: Template) -> Callable[[Stamp], np.ndarray | None]:
    """Injection hook for pxs.movers.layers.make_layer."""
    w = grid.wcs()

    def add(s: Stamp) -> np.ndarray | None:
        out = np.zeros(s.image.shape, float)
        for src in sources:
            gx, gy = position_px(src, geom, s.mjd)
            ra, dec = w.all_pix2world(gx, gy, 0)
            x, y = s.pixel_of(float(ra), float(dec))
            lx, ly = x - s.x0, y - s.y0
            if not (0 <= lx < s.image.shape[1] and 0 <= ly < s.image.shape[0]):
                continue
            wave, _ = s.wave_at_pixel(x, y)
            f = src.flux_mjy * float(template(np.array([wave]))[0])
            out += psf_model(s, x, y) * (f / config.MJYSR_TO_MJY)
        return out if np.any(out) else None

    return add


def draw_sources(rng: np.random.Generator, n: int, grid: Grid, geom: PassGeometry,
                 flux_range_mjy: tuple[float, float], d_range_au: tuple[float, float],
                 margin_px: int = 12, min_sep_px: float = 20.0) -> list[Synthetic]:
    """n movers: log-uniform flux and distance, uniform own-velocity direction and speed
    up to SPEED_FACTOR x circular, start positions at least min_sep_px apart whose tracks
    stay margin_px inside the grid."""
    scale = 1.0 / (geom.pixscale_arcsec * RAD_PER_ARCSEC)
    out: list[Synthetic] = []
    tries = 0
    while len(out) < n and tries < 200 * n:
        tries += 1
        d = float(np.exp(rng.uniform(*np.log(d_range_au))))
        vmax = SPEED_FACTOR * AU_PER_DAY_CIRC_1AU / np.sqrt(d) / d * scale
        r, a = vmax * np.sqrt(rng.uniform()), rng.uniform(0, 2 * np.pi)
        vx, vy = geom.reflex_px_day / d + r * np.array([np.cos(a), np.sin(a)])
        x, y = rng.uniform(margin_px, grid.size_px - margin_px, 2)
        tx = x + vx * geom.dt + geom.curve_px[0] / d
        ty = y + vy * geom.dt + geom.curve_px[1] / d
        if tx.min() < margin_px or ty.min() < margin_px or max(tx.max(), ty.max()) > \
                grid.size_px - margin_px:
            continue
        if any(np.hypot(x - o.x, y - o.y) < min_sep_px for o in out):
            continue
        f = float(np.exp(rng.uniform(*np.log(flux_range_mjy))))
        out.append(Synthetic(float(x), float(y), d, float(vx), float(vy), f))
    return out
