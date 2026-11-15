"""Vectorised sky -> pixel for the TAN-SIP WCS stored in the frame index.

A SPHEREx Level-2 image is a gnomonic (TAN) projection with SIP distortion. Testing whether
a position falls on a frame only needs the inverse direction, so this module implements it
in numpy for thousands of frames at once, from the numbers the index stores:

    (ra, dec) --TAN--> (xi, eta) deg --CD^-1--> (U, V) px --SIP AP/BP--> (u, v) px
    pixel = CRPIX + (u, v)                      (FITS 1-based pixel coordinates)

The result agrees with astropy's `all_world2pix` to well under 0.01 px over the detector
(checked in tests/spherex/test_spx_indexwcs.py and, for every frame, at build time).
Only LONPOLE = 180 deg (the TAN default for CRVAL2 < 90 deg) is supported.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_DEG = np.pi / 180.0


def sip_terms(order: int) -> tuple[tuple[int, int], ...]:
    """The (p, q) exponents of a SIP polynomial of the given order, p + q <= order."""
    return tuple((p, q) for p in range(order + 1) for q in range(order + 1 - p))


@dataclass(frozen=True)
class WcsTable:
    """Inverse-WCS parameters of n frames. Every array has length n except ap and bp.

    cd is the 2x2 matrix mapping pixel offsets to intermediate world degrees
    (PC * CDELT). ap and bp have shape (n, len(sip_terms(order))); zeros mean no SIP.
    """

    crval1: np.ndarray
    crval2: np.ndarray
    crpix1: np.ndarray
    crpix2: np.ndarray
    cd11: np.ndarray
    cd12: np.ndarray
    cd21: np.ndarray
    cd22: np.ndarray
    ap: np.ndarray
    bp: np.ndarray
    order: int

    def take(self, idx: np.ndarray) -> WcsTable:
        """The rows `idx` (integer or boolean index) as a new table."""
        return WcsTable(
            self.crval1[idx], self.crval2[idx], self.crpix1[idx], self.crpix2[idx],
            self.cd11[idx], self.cd12[idx], self.cd21[idx], self.cd22[idx],
            self.ap[idx], self.bp[idx], self.order,
        )


def _poly(coef: np.ndarray, order: int, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """sum_k coef[:, k] * u**p_k * v**q_k for the SIP terms of `order`."""
    out = np.zeros_like(u)
    if coef.shape[1] == 0:
        return out
    up = [np.ones_like(u)]
    vp = [np.ones_like(v)]
    for _ in range(order):
        up.append(up[-1] * u)
        vp.append(vp[-1] * v)
    for k, (p, q) in enumerate(sip_terms(order)):
        out += coef[:, k] * up[p] * vp[q]
    return out


def sky_to_pixel(ra_deg: float | np.ndarray, dec_deg: float | np.ndarray,
                 t: WcsTable) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """FITS pixel (x, y) of the sky position(s) on each frame of `t`, and a validity mask.

    ra_deg and dec_deg are scalars or arrays of length n (one position per frame). The mask
    is False where the position is 90 deg or more from the frame's reference point, where
    the TAN projection is undefined; x and y are NaN there.
    """
    a = np.asarray(ra_deg, dtype=float) * _DEG
    d = np.asarray(dec_deg, dtype=float) * _DEG
    a0 = t.crval1 * _DEG
    d0 = t.crval2 * _DEG
    da = a - a0
    cos_d, sin_d = np.cos(d), np.sin(d)
    cosc = np.sin(d0) * sin_d + np.cos(d0) * cos_d * np.cos(da)
    ok = cosc > 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = np.where(ok, cos_d * np.sin(da) / cosc, np.nan) / _DEG
        eta = np.where(ok, (np.cos(d0) * sin_d - np.sin(d0) * cos_d * np.cos(da)) / cosc,
                       np.nan) / _DEG
        det = t.cd11 * t.cd22 - t.cd12 * t.cd21
        uu = (t.cd22 * xi - t.cd12 * eta) / det
        vv = (-t.cd21 * xi + t.cd11 * eta) / det
    x = uu + _poly(t.ap, t.order, uu, vv)
    y = vv + _poly(t.bp, t.order, uu, vv)
    return x + t.crpix1, y + t.crpix2, ok


def distance_to_box(x: np.ndarray, y: np.ndarray, n1: np.ndarray, n2: np.ndarray) -> np.ndarray:
    """Pixel distance from (x, y) to the image rectangle [0.5, n+0.5]^2 (0 inside it)."""
    dx = np.maximum(np.maximum(0.5 - x, x - (n1 + 0.5)), 0.0)
    dy = np.maximum(np.maximum(0.5 - y, y - (n2 + 0.5)), 0.0)
    return np.hypot(dx, dy)
