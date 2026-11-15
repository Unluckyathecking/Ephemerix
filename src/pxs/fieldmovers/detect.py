"""Every source of every WISE visit of one band, as positions on the common grid.

A source is a local maximum of the matched-filter S/N map at or above SNR_MIN (the same map
and peak rule the target's own centroid uses, `centroid._prepare` and `centroid._peaks`; the
limit is lower than the centroid's 5 because a track needs many visits), with its
position refined to a fraction of a pixel by a parabola through the peak and its neighbours.
Saturated cores are kept as sources at the centre of the core. Peaks closer than EDGE_FWHM
PSF widths to the image edge are dropped: half their light is off the image.

The position error of a visit is ERR_K[band] sigma_psf / (S/N) in quadrature with
FLOOR_ARCSEC; a saturated core gets SATURATED_ARCSEC. Both constants are the measured scatter
of static sources about their own fitted tracks, after registration, in the 17 gallery
fields (186 W2 and 336 W1 tracks of S/N 5 and up, seen in 15 or more visits): rms per axis
times S/N is 2.0-2.6 px in W2 and 1.2-1.6 px in W1 at S/N 5-25, and the scatter levels off
at 0.02-0.03" above S/N 200. (The white-noise limit, sqrt(2) sigma_psf / (S/N), is about
twice that: the noise of the resampled frames is correlated.) Written with Claude Code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pxs import centroid
from pxs.astrometry import decimal_year
from pxs.grid import Grid, Stack

SNR_MIN = 4.0  # package docstring
EDGE_FWHM = 1.0
ERR_K = {"W2": 0.8, "W1": 0.55}  # module docstring
FLOOR_ARCSEC = 0.03
SATURATED_ARCSEC = 2.0  # a core's outline is off-centre by up to 4" (centroid docstring)
SATURATED_SNR = 1000.0  # stands in for the unknown S/N of a saturated core


@dataclass(frozen=True)
class Epochs:
    """The sources of each visit, visits in time order. Positions in edge-convention pixels."""

    band: str
    ids: tuple[str, ...]
    years: np.ndarray  # (n_epochs,)
    xy: tuple[np.ndarray, ...]  # per epoch (m, 2)
    snr: tuple[np.ndarray, ...]  # per epoch (m,)
    err_px: tuple[np.ndarray, ...]  # per epoch (m,), 1 sigma per axis
    pixscale_arcsec: float
    size_px: int


def _vertex(lo: float, mid: float, hi: float) -> float:
    """Offset (-0.5 to 0.5 px) of the maximum of the parabola through three samples."""
    den = lo - 2.0 * mid + hi
    if not np.isfinite(den) or den >= 0.0:
        return 0.0
    return float(np.clip(0.5 * (lo - hi) / den, -0.5, 0.5))


def _refined(snr: np.ndarray, peak: tuple[float, float, float]) -> tuple[float, float]:
    i, j = int(peak[1]), int(peak[0])
    ny, nx = snr.shape
    if not (0 < i < ny - 1 and 0 < j < nx - 1):
        return peak[0], peak[1]
    return (peak[0] + _vertex(snr[i, j - 1], snr[i, j], snr[i, j + 1]),
            peak[1] + _vertex(snr[i - 1, j], snr[i, j], snr[i + 1, j]))


def _sources(stack: Stack, pixscale: float,
             band: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(xy, snr, err_px) of one visit."""
    fr = centroid._prepare(stack, pixscale)
    ny, nx = fr.snr.shape
    edge = EDGE_FWHM * fr.fwhm_px
    rows = []
    for p in centroid._peaks(fr, (nx / 2.0, ny / 2.0), float(nx + ny), SNR_MIN):
        if not (edge <= p[0] <= nx - edge and edge <= p[1] <= ny - edge):
            continue
        if math.isinf(p[2]):
            rows.append((p[0], p[1], SATURATED_SNR, SATURATED_ARCSEC / pixscale))
            continue
        x, y = _refined(fr.snr, p)
        err = math.hypot(ERR_K[band] * fr.sigma_px / p[2], FLOOR_ARCSEC / pixscale)
        rows.append((x, y, p[2], err))
    a = np.array(rows, float).reshape(-1, 4)
    return a[:, :2], a[:, 2], a[:, 3]


def epochs(stacks: Sequence[tuple[str, Stack]], ids: Sequence[str], grid: Grid,
           band: str) -> Epochs:
    """The sources of every WISE visit of `band` that has any data, in time order."""
    use = sorted(((st.mjd, fid, st) for fid, (b, st) in zip(ids, stacks)
                  if st.mission == "WISE" and b == band and np.isfinite(st.image).any()),
                 key=lambda r: r[0])
    found = [_sources(st, grid.pixscale_arcsec, band) for _, _, st in use]
    return Epochs(band=band, ids=tuple(fid for _, fid, _ in use),
                  years=np.array([float(decimal_year(m)) for m, _, _ in use]),
                  xy=tuple(f[0] for f in found), snr=tuple(f[1] for f in found),
                  err_px=tuple(f[2] for f in found),
                  pixscale_arcsec=grid.pixscale_arcsec, size_px=grid.size_px)


def scrambled(ep: Epochs, rng: np.random.Generator) -> Epochs:
    """The same visits with their dates dealt out at random: the null of the search. Static
    sources stay static, a real mover no longer lies on a straight line in time."""
    order = rng.permutation(len(ep.years))  # visit order[k] takes the k-th date
    return Epochs(band=ep.band, ids=tuple(ep.ids[i] for i in order), years=ep.years,
                  xy=tuple(ep.xy[i] for i in order), snr=tuple(ep.snr[i] for i in order),
                  err_px=tuple(ep.err_px[i] for i in order),
                  pixscale_arcsec=ep.pixscale_arcsec, size_px=ep.size_px)
