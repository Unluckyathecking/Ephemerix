"""Trajectories of distant bodies seen from Earth within one SPHEREx pass.

A body at geocentric distance d (au) moving linearly with barycentric velocity U, seen by an
observer at Earth E(t), has tangent-plane offset from its mid-pass position

    delta(t) = v (t - t0) - perp(E_nl(t)) / d,

where E_nl(t) = E(t) - E(t0) - E'(t0) (t - t0) is the non-linear (curved) part of Earth's
path and v = perp(U - E'(t0)) / d is the linear sky rate. The first term is a free 2-D rate;
the second is the parallax curvature that ties the trajectory to a distance. Neglected:
SPHEREx's orbit (700 km: <= 0.3" at 30 au), the body's orbital curvature (< 0.1" over
two weeks at 30 au), light time, and the 0.4% change of d over a pass (< 0.2 px).

Rates are in grid px/day, offsets in grid px. Grid convention (pxs.grid): north up, east
left, so +x is west and +y is south.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from astropy.coordinates import get_body_barycentric_posvel
from astropy.time import Time

AU_PER_DAY_CIRC_1AU = 0.0172021  # circular speed at 1 au, au/day (Gaussian constant)
SPEED_FACTOR = 1.5  # intrinsic speed allowed: 1.5 x circular (escape is 1.414 x)
MAX_POS_ERR_PX = 0.5  # worst-case offset error at the pass ends between grid trials
D_MIN_AU, D_MAX_AU = 30.0, 1000.0
RAD_PER_ARCSEC = math.pi / 180 / 3600


def tangent_basis(ra: float, dec: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unit vectors (n, east, north) at (ra, dec) degrees, ICRS equatorial."""
    a, d = math.radians(ra), math.radians(dec)
    n = np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])
    east = np.array([-math.sin(a), math.cos(a), 0.0])
    north = np.cross(n, east)
    return n, east, north


def earth_posvel(mjd: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Earth's barycentric position (au) and velocity (au/day), shape (3, n), ICRS axes."""
    pos, vel = get_body_barycentric_posvel("earth", Time(np.asarray(mjd, float), format="mjd",
                                                         scale="tdb"))
    return pos.xyz.to_value("au"), vel.xyz.to_value("au/day")


@dataclass(frozen=True)
class PassGeometry:
    """Per-frame quantities for one field and pass.

    dt: t_i - t0 (days). curve_px: (2, n) offsets in px of -perp(E_nl)/d at d = 1 au,
    so the curvature term at distance d is curve_px / d. reflex_px_day: (2,) sky rate in
    px/day of a body at rest at d = 1 au (the reflex rate is reflex_px_day / d).
    """

    t0: float
    dt: np.ndarray
    curve_px: np.ndarray
    reflex_px_day: np.ndarray
    pixscale_arcsec: float

    @property
    def half_span_days(self) -> float:
        return float(np.max(np.abs(self.dt))) if self.dt.size else 0.0

    def offsets(self, d_au: float, v_px_day: np.ndarray) -> np.ndarray:
        """(2, n) px offsets of a trajectory with distance d and linear rate v."""
        return np.outer(np.asarray(v_px_day, float), self.dt) + self.curve_px / d_au


def _to_grid_px(vec_au: np.ndarray, east: np.ndarray, north: np.ndarray,
                pixscale: float) -> np.ndarray:
    """Tangent-plane components of 3-vectors (3, n) at 1 au, as grid px (+x west, +y south)."""
    scale = 1.0 / (pixscale * RAD_PER_ARCSEC)
    return np.vstack([-(east @ vec_au) * scale, -(north @ vec_au) * scale])


def pass_geometry(ra: float, dec: float, mjd: np.ndarray, pixscale_arcsec: float,
                  t0: float | None = None) -> PassGeometry:
    """Geometry for frames at `mjd` of a field centred on (ra, dec)."""
    mjd = np.asarray(mjd, float)
    t0 = float(0.5 * (mjd.min() + mjd.max())) if t0 is None else float(t0)
    _, east, north = tangent_basis(ra, dec)
    pos, _ = earth_posvel(mjd)
    p0, v0 = earth_posvel(np.array([t0]))
    dt = mjd - t0
    e_nl = pos - p0 - v0 * dt
    # Apparent offset is -(observer displacement)/d.
    curve = _to_grid_px(-e_nl, east, north, pixscale_arcsec)
    reflex = _to_grid_px(-v0, east, north, pixscale_arcsec)[:, 0]
    return PassGeometry(t0, dt, curve, reflex, pixscale_arcsec)


@dataclass(frozen=True)
class TrajectoryGrid:
    """Trial trajectories: distance d (au) and linear rate (vx, vy) in px/day, one row each."""

    d_au: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    dv_px_day: float

    def __len__(self) -> int:
        return int(self.d_au.size)


def distance_grid(geom: PassGeometry, d_min: float = D_MIN_AU,
                  d_max: float = D_MAX_AU) -> np.ndarray:
    """Distances spaced evenly in 1/d so the curvature term errs by <= MAX_POS_ERR_PX."""
    cmax = float(np.max(np.hypot(*geom.curve_px))) if geom.dt.size else 0.0
    if cmax == 0.0:
        return np.array([d_min])
    step = 2 * MAX_POS_ERR_PX / cmax  # nearest grid value is at most half a step away
    inv = np.arange(1 / d_max, 1 / d_min + step, step)
    return np.sort(1.0 / inv[inv > 0])[::-1].clip(d_min, d_max)


def allowed_radius_px_day(d_au: float, pixscale_arcsec: float) -> float:
    """Largest own rate (px/day) of a bound body at d_au: SPEED_FACTOR x circular speed."""
    scale = 1.0 / (pixscale_arcsec * RAD_PER_ARCSEC)
    return SPEED_FACTOR * AU_PER_DAY_CIRC_1AU / math.sqrt(d_au) / d_au * scale


def _disk_points(centre: np.ndarray, radius: float, dv: float) -> np.ndarray:
    """(k, 2) points of the global lattice (step dv, anchored at 0) within radius + dv/2."""
    lo = np.floor((centre - radius) / dv - 1).astype(int)
    hi = np.ceil((centre + radius) / dv + 1).astype(int)
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0] + 1) * dv, np.arange(lo[1], hi[1] + 1) * dv)
    inside = np.hypot(gx - centre[0], gy - centre[1]) <= radius + 0.5 * dv
    return np.column_stack([gx[inside], gy[inside]])


def trajectory_grid(geom: PassGeometry, d_min: float = D_MIN_AU,
                    d_max: float = D_MAX_AU) -> TrajectoryGrid:
    """Rates on a square lattice of step dv (worst-case end-of-pass offset error, half the
    lattice diagonal times the half-span, is MAX_POS_ERR_PX), covering every distance in
    [d_min, d_max]: the allowed-rate disk (around reflex/d, radius allowed_radius) of every d.

    Each node of distance_grid owns the 1/d interval half-way to its neighbours and the union
    of the disks swept across it (sampled finely enough that the disk centre moves < dv);
    its trials use the node's curvature term, which distance_grid bounds. Disks of the nodes
    alone leave holes between them (115-900 au in a 9-day pass, found by injections)."""
    half = max(geom.half_span_days, 0.5)
    dv = 2 * MAX_POS_ERR_PX / (math.sqrt(2) * half)
    nodes = distance_grid(geom, d_min, d_max)
    inv = 1.0 / nodes
    edges = np.concatenate([[1 / d_max], 0.5 * (inv[1:] + inv[:-1]), [1 / d_min]])
    reflex = float(np.hypot(*geom.reflex_px_day))
    step = dv / reflex if reflex > 0 else np.inf
    rows = []
    for i, d in enumerate(nodes):
        n_sub = max(2, math.ceil((edges[i + 1] - edges[i]) / step) + 1)
        pts = np.vstack([_disk_points(geom.reflex_px_day * u,
                                      allowed_radius_px_day(1 / u, geom.pixscale_arcsec), dv)
                         for u in np.linspace(edges[i], edges[i + 1], n_sub)])
        pts = np.unique(np.round(pts / dv).astype(np.int64), axis=0) * dv
        rows.append(np.column_stack([np.full(len(pts), d), pts]))
    a = np.vstack(rows)
    return TrajectoryGrid(a[:, 0], a[:, 1], a[:, 2], dv)


def implied_distance_range(grid: TrajectoryGrid, vx: float, vy: float,
                           geom: PassGeometry) -> tuple[float, float]:
    """Range of distances (au) whose allowed-rate disk contains (vx, vy): broad by nature.
    Tested on a fine grid in 1/d over the grid's span, not only at its nodes."""
    lo, hi = float(np.min(grid.d_au)), float(np.max(grid.d_au))
    ds = 1.0 / np.linspace(1 / hi, 1 / lo, 2000)
    ok = [d for d in ds if math.hypot(vx - geom.reflex_px_day[0] / d,
                                      vy - geom.reflex_px_day[1] / d)
          <= allowed_radius_px_day(d, geom.pixscale_arcsec) + grid.dv_px_day]
    return (float(min(ok)), float(max(ok))) if ok else (math.nan, math.nan)
