"""Synthetic exposure stacks for offline tests of the mover search (no network)."""

from __future__ import annotations

import numpy as np
import pytest

from pxs.grid import Grid
from pxs.movers.geometry import PassGeometry, pass_geometry
from pxs.movers.layers import KERNEL_HALF, Layer, field_grid
from pxs.spherex.types import Frame

RA, DEC = 150.0, 35.0  # ecliptic latitude ~ +22 deg: a few px/day of reflex at 50 au
N_FRAMES = 30
SIGMA = 0.01  # MJy/sr per pixel
PSF_SIGMA_PX = 0.8


def gaussian_kernel(dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    k = KERNEL_HALF
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    g = np.exp(-((xx - dx) ** 2 + (yy - dy) ** 2) / (2 * PSF_SIGMA_PX ** 2))
    return g / g.sum()


def paint(img: np.ndarray, x: float, y: float, amp: float) -> np.ndarray:
    """Add amp x PSF centred on pixel-index position (x, y); returns a new array."""
    out = img.copy()
    k = KERNEL_HALF
    ix, iy = round(x), round(y)
    ker = amp * gaussian_kernel(x - ix, y - iy)
    h, w = img.shape
    for j in range(-k, k + 1):
        for i in range(-k, k + 1):
            if 0 <= iy + j < h and 0 <= ix + i < w:
                out[iy + j, ix + i] += ker[j + k, i + k]
    return out


class Sky:
    """A field with noise layers for one search pass and one reference pass."""

    def __init__(self, seed: int = 0, size_arcmin: float = 8.0) -> None:
        self.rng = np.random.default_rng(seed)
        self.grid: Grid = field_grid(RA, DEC, size_arcmin)
        self.mjd = np.sort(60850.0 + self.rng.uniform(0, 10, N_FRAMES))
        self.ref_mjd = self.mjd + 180.0
        self.geom: PassGeometry = pass_geometry(RA, DEC, self.mjd, self.grid.pixscale_arcsec)
        self.waves = np.linspace(0.95, 1.05, N_FRAMES)

    def _layer(self, i: int, mjd: float, img: np.ndarray, det: int) -> Layer:
        n = self.grid.size_px
        frame = Frame("synthetic", f"obs{i}_{mjd:.3f}", det, mjd, f"key{i}_{mjd:.3f}", 0.75, 1.1)
        return Layer(frame, mjd, img.astype(np.float32),
                     np.full((n, n), SIGMA ** 2, np.float32),
                     np.full((n, n), self.waves[i % N_FRAMES], np.float32),
                     np.full((n, n), 0.05, np.float32), gaussian_kernel().astype(np.float32))

    def noise(self) -> np.ndarray:
        n = self.grid.size_px
        return self.rng.normal(0, SIGMA, (n, n))

    def layers(self, movers=(), statics=()) -> tuple[list[Layer], list[Layer]]:
        """(search, refs). movers: (x, y, d_au, vx, vy, amp); statics: (x, y, amp)."""
        search, refs = [], []
        for i, m in enumerate(self.mjd):
            img = self.noise()
            for x, y, amp in statics:
                img = paint(img, x, y, amp)
            for x, y, d, vx, vy, amp in movers:
                dt = m - self.geom.t0
                img = paint(img, x + vx * dt + self.geom.curve_px[0, i] / d,
                            y + vy * dt + self.geom.curve_px[1, i] / d, amp)
            search.append(self._layer(i, m, img, 1))
        for i, m in enumerate(self.ref_mjd):
            img = self.noise()
            for x, y, amp in statics:
                img = paint(img, x, y, amp)
            refs.append(self._layer(i, m, img, 1))
        return search, refs


@pytest.fixture
def sky() -> Sky:
    return Sky()
