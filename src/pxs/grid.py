"""The common image grid every frame in a view is resampled onto, and the stack type
the data modules hand to the renderer. Written with Claude Code.

Conventions (see docs/api.md): north up, east left, square, centred on the query
position and fixed on the sky. Arrays are in display orientation: ``image[y, x]`` with
row 0 at the top (north) and column 0 at the left (east). Pixel coordinates use pixel
edges, so the top-left corner is (0, 0) and the grid centre is (size_px/2, size_px/2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.wcs import WCS


@dataclass(frozen=True)
class Grid:
    """A north-up tangent-plane grid. Angles in degrees, field of view in arcsec."""

    center_ra: float
    center_dec: float
    fov_arcsec: float
    size_px: int

    @property
    def pixscale_arcsec(self) -> float:
        return self.fov_arcsec / self.size_px

    @property
    def shape(self) -> tuple[int, int]:
        return (self.size_px, self.size_px)

    def wcs(self) -> WCS:
        """Astropy WCS for arrays in display orientation (y grows southwards)."""
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [self.center_ra, self.center_dec]
        # Edge coordinate size/2 is FITS 1-based pixel coordinate size/2 + 0.5.
        w.wcs.crpix = [self.size_px / 2 + 0.5, self.size_px / 2 + 0.5]
        scale = self.pixscale_arcsec / 3600.0
        w.wcs.cdelt = [-scale, -scale]
        w.array_shape = self.shape
        return w

    def sky_to_px(self, ra, dec) -> tuple[np.ndarray, np.ndarray]:
        """Edge-convention pixel coordinates (x, y) of sky positions in degrees."""
        x, y = self.wcs().all_world2pix(ra, dec, 0)
        return x + 0.5, y + 0.5


@dataclass(frozen=True)
class Stack:
    """One epoch's image on a Grid, ready to render.

    image: float32, shape grid.shape, display orientation, NaN where there is no data.
    unit: surface brightness or flux unit of ``image`` (for the record; rendering is relative).
    mjd: mean observation time of the exposures used.
    flag_fraction: share of contributing pixels dropped by quality flags (0 to 1).
    warnings: short plain phrases, e.g. "saturated".
    saturated_mask: bool array of shape grid.shape, True where the detector saturated (the
        pixel value there is a fill, not a measurement), or None when the source does not
        say. The centroid ignores these pixels and the renderer draws them white.
    """

    image: np.ndarray
    mission: str  # "WISE" or "SPHEREx"
    band: str  # short label, e.g. "W2" or "4.4-5.0 um"
    wavelength_um: tuple[float, float]
    mjd: float
    date_span_days: float
    n_exposures: int
    native_pixscale_arcsec: float
    flag_fraction: float = 0.0
    warnings: tuple[str, ...] = ()
    unit: str = "MJy/sr"
    saturated_mask: np.ndarray | None = None


def reproject_to_grid(data: np.ndarray, wcs_in: WCS, grid: Grid,
                      min_good_weight: float | None = None) -> np.ndarray:
    """Resample a 2-D image with its WCS onto ``grid``; NaN outside the input footprint.

    By default NaN input pixels make every grid pixel they touch NaN (plain bilinear). With
    ``min_good_weight`` (0-1], interpolation is normalised instead: the data with NaN set to
    0 and the good-pixel mask are resampled alike and divided, and a grid pixel is NaN only
    where good pixels carry less than that share of its weight. Plain resampling spreads
    each bad native pixel over about 4 native pixels of grid area.
    """
    from reproject import reproject_interp

    if min_good_weight is None:
        out, footprint = reproject_interp((data, wcs_in), grid.wcs(), shape_out=grid.shape)
        return np.where(footprint > 0, out, np.nan).astype(np.float32)
    if not 0.0 < min_good_weight <= 1.0:
        raise ValueError(f"min_good_weight must be in (0, 1], got {min_good_weight}")
    good = np.isfinite(data)
    values = reproject_to_grid(np.where(good, data, 0.0), wcs_in, grid)
    weight = reproject_to_grid(good.astype(np.float32), wcs_in, grid)
    usable = np.isfinite(weight) & (np.nan_to_num(weight) >= min_good_weight)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(usable, values / weight, np.nan).astype(np.float32)
