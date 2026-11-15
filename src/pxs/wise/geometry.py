"""Footprint geometry: is a sky position inside a frame, by how much, and which grid points
must a frame cover. Angles in degrees unless a name says arcsec.
"""

from __future__ import annotations

import numpy as np

from pxs.astrometry import px_to_sky, sky_to_px
from pxs.grid import Grid
from pxs.wise.frames import Corners


def offsets_arcsec(ra, dec, ra0: float, dec0: float) -> tuple[np.ndarray, np.ndarray]:
    """Gnomonic offsets (east, north) in arcsec of (ra, dec) about (ra0, dec0)."""
    # On a 1"/px, 1-pixel grid the centre is at 0.5 and x grows westwards, y southwards.
    x, y = sky_to_px(np.asarray(ra, float), np.asarray(dec, float), ra0, dec0, 1.0, 1)
    return 0.5 - x, 0.5 - y


def edge_distance_arcsec(corners: Corners, ra: float, dec: float) -> float:
    """Signed distance in arcsec from (ra, dec) to the nearest edge of a convex footprint:
    positive inside, negative outside."""
    xs, ys = offsets_arcsec([c[0] for c in corners], [c[1] for c in corners], ra, dec)
    x2, y2 = np.roll(xs, -1), np.roll(ys, -1)
    area2 = float(np.sum(xs * y2 - x2 * ys))  # twice the signed area, sign = orientation
    if area2 == 0:
        return -np.inf
    lengths = np.hypot(x2 - xs, y2 - ys)
    # Signed distance of the origin from each edge line, positive on the interior side.
    cross = (xs * y2 - x2 * ys) / np.where(lengths > 0, lengths, np.inf)
    return float(np.min(cross * np.sign(area2)))


def grid_corners(grid: Grid) -> list[tuple[float, float]]:
    """Sky positions of the four outer corners of a grid."""
    n = grid.size_px
    ras, decs = px_to_sky([0, n, n, 0], [0, 0, n, n], grid.center_ra, grid.center_dec,
                          grid.fov_arcsec, n)
    return list(zip(ras.tolist(), decs.tolist()))


def grid_border(grid: Grid, per_side: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """Sky positions sampled along the grid border (corners included), for range planning."""
    n = grid.size_px
    t = np.linspace(0.0, n, per_side)
    zeros, full = np.zeros_like(t), np.full_like(t, n)
    x = np.concatenate([t, full, t, zeros])
    y = np.concatenate([zeros, t, full, t])
    return px_to_sky(x, y, grid.center_ra, grid.center_dec, grid.fov_arcsec, n)


def covers_grid(corners: Corners, grid: Grid) -> bool:
    """True when all four grid corners fall inside the frame footprint."""
    return all(edge_distance_arcsec(corners, ra, dec) > 0 for ra, dec in grid_corners(grid))
