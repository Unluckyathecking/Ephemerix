"""Synthetic stacks, spectra and fake data sources implementing the pxs.sources protocols."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from pxs.astrometry import decimal_year, propagate
from pxs.grid import Grid, Stack
from pxs.sources import Target
from pxs.typing import load_templates

GRID = Grid(center_ra=133.78, center_dec=-7.244, fov_arcsec=240.0, size_px=240)
MOVER = Target(name="Fast mover", ra=133.7835555, dec=-7.244052, epoch=2015.405,
               pmra_masyr=-8123.7, pmdec_masyr=673.2, slug="fast-mover", blurb="A test.",
               known_type="Y4")
WISE_PIX = 2.75
SPX_PIX = 6.2


def gaussian_stack(grid: Grid, xy: tuple[float, float] | None, mjd: float, *, amp: float = 60.0,
                   noise: float = 1.0, background: float = 10.0, seed: int = 0,
                   mission: str = "WISE", native: float = WISE_PIX, fwhm_arcsec: float = 6.2,
                   warnings: tuple[str, ...] = ()) -> Stack:
    """Noise plus a Gaussian at edge-convention pixel position `xy` (None: noise only)."""
    rng = np.random.default_rng(seed)
    img = background + noise * rng.standard_normal(grid.shape)
    if xy is not None:
        i, j = np.mgrid[: grid.size_px, : grid.size_px]
        s = fwhm_arcsec / 2.3548 / grid.pixscale_arcsec
        img += amp * np.exp(-((j + 0.5 - xy[0]) ** 2 + (i + 0.5 - xy[1]) ** 2) / (2 * s * s))
    return Stack(image=img.astype(np.float32), mission=mission, band="test",
                 wavelength_um=(4.0, 5.2), mjd=mjd, date_span_days=1.0, n_exposures=12,
                 native_pixscale_arcsec=native, warnings=warnings)


def true_xy(grid: Grid, target: Target, mjd: float, pm_scale: float = 1.0):
    ra, dec = propagate(target.ra, target.dec, target.epoch, target.pmra_masyr * pm_scale,
                        target.pmdec_masyr * pm_scale, float(decimal_year(mjd)))
    x, y = grid.sky_to_px(ra, dec)
    return float(x), float(y)


@dataclass(frozen=True)
class FakeSpecPoint:
    wl_um: float
    bw_um: float
    flux_mjy: float | None
    err_mjy: float | None
    detector: int
    flagged: bool
    mjd: float


class FakeWise:
    """Eight visits 2010-2024; the source moves with `pm_scale` times the catalogue motion."""

    def __init__(self, target: Target, pm_scale: float = 1.0, fail: bool = False):
        self.target, self.pm_scale, self.fail = target, pm_scale, fail

    def find_visits(self, ra: float, dec: float) -> list[float]:
        if self.fail:
            raise ConnectionError("IRSA timed out")
        return [55300.0 + 730.5 * k for k in range(8)]

    def stack_visit(self, visit: float, band: str, grid: Grid) -> Stack | None:
        xy = true_xy(grid, self.target, visit, self.pm_scale)
        seed = int(visit) + (1 if band == "W1" else 2)
        return gaussian_stack(grid, xy, visit, seed=seed, amp=40.0 if band == "W1" else 80.0)


class FakePass(list):
    """A pass as a list of frame MJDs, with the pass epoch attributes of pxs.spherex.Pass."""

    @property
    def mjd_start(self) -> float:
        return self[0]

    @property
    def mjd_end(self) -> float:
        return self[-1]


class FakeSpherex:
    """Two passes in 2025; stacks in every window and a T8-shaped spectrum per pass."""

    def __init__(self, target: Target):
        self.target = target

    def find_frames(self, ra: float, dec: float) -> list[float]:
        return [60700.0, 60702.0, 60880.0, 60883.0]

    def group_passes(self, frames: list[float]) -> list[FakePass]:
        return [FakePass(frames[:2]), FakePass(frames[2:])]

    def stack_pass(self, pas, grid, window_um, target=None) -> Stack | None:
        mjd = float(np.mean(pas))
        st = gaussian_stack(grid, true_xy(grid, self.target, mjd), mjd, mission="SPHEREx",
                            native=SPX_PIX, fwhm_arcsec=13.0, seed=int(mjd) + int(window_um[0]))
        return replace(st, band="label from module", wavelength_um=window_um)

    def extract_spectrum(self, pas, target, neighbours=None) -> list[FakeSpecPoint]:
        t = load_templates()["T8"]
        wl = t.wl_um[::3]
        flux = np.interp(wl, t.wl_um, t.flam) * wl**2
        flux = flux / flux.max()
        rng = np.random.default_rng(int(pas[0]))
        pts = [FakeSpecPoint(float(w), float(w / 40), float(f + 0.02 * rng.standard_normal()),
                             0.02, 1 + int(w), False, float(pas[0])) for w, f in zip(wl, flux)]
        pts[3] = FakeSpecPoint(pts[3].wl_um, pts[3].bw_um, None, None, 1, True, pts[3].mjd)
        return pts


def no_overlays(grid: Grid):
    return {"gaia": [], "catwise": []}, []
