"""Combine background-subtracted frames already on a common grid into one image.

1. Drop whole frames whose robust background noise exceeds ``NOISE_FACTOR`` x the median of
   the visit (bad or streaked frames).
2. Per pixel, clip values more than ``CLIP_SIGMA`` robust sigmas from the median across frames
   (cosmic rays, satellite trails, glints), then average what is left.
3. Pixels covered by enough frames but NaN in all of them are filled (``fill_holes``): a hole
   ringed by bright pixels (a saturated core; fatal mask bits are NaN in the L1b int image)
   becomes a plateau at the ring's maximum, any other hole takes the ring's median. Pixels NaN
   in SATURATED_SHARE of their frames are reported in ``saturated``; the renderer and the
   centroid decide from the ring which of those are real saturated cores.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clip
from astropy.utils.exceptions import AstropyUserWarning
from scipy import ndimage

NOISE_FACTOR = 2.0
CLIP_SIGMA = 3.0
MIN_FRAMES_TO_CLIP = 3
# A pixel counts as saturated when flagged in this share of the frames covering it. Bad pixels
# hit the same sky spot only in frames from one scan direction (about half), so 0.5 is too low.
SATURATED_SHARE = 0.8
BRIGHT_RING_SIGMA = 10.0  # ring median this many robust sigmas above sky: a saturated core


@dataclass(frozen=True)
class Combined:
    """Result of combining N layers. ``kept`` indexes the layers that were used."""

    image: np.ndarray  # float32, NaN where no frame covers the pixel
    kept: tuple[int, ...]
    flag_fraction: float  # share of covered input pixels that were NaN (flagged)
    saturated: np.ndarray  # bool: NaN in SATURATED_SHARE of the frames covering it
    covered: np.ndarray  # bool: covered by at least one kept frame


def robust_sigma(values: np.ndarray) -> float:
    """1.4826 x median absolute deviation of the finite values; inf if there are none."""
    v = values[np.isfinite(values)]
    if v.size == 0:
        return float("inf")
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def reject_noisy(layers: Sequence[np.ndarray]) -> list[int]:
    """Indices of layers whose noise is within NOISE_FACTOR of the median layer noise."""
    noise = np.array([robust_sigma(x) for x in layers])
    finite = np.isfinite(noise)
    if not finite.any():
        return []
    limit = NOISE_FACTOR * np.median(noise[finite])
    return [i for i, n in enumerate(noise) if n <= limit]


def clipped_mean(cube: np.ndarray) -> np.ndarray:
    """Per-pixel mean across axis 0 after median/MAD sigma clipping; NaN inputs are ignored."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns
        warnings.simplefilter("ignore", AstropyUserWarning)  # NaN inputs are expected
        if cube.shape[0] < MIN_FRAMES_TO_CLIP:
            return np.nanmean(cube, axis=0)
        clipped = sigma_clip(cube, sigma=CLIP_SIGMA, maxiters=3, cenfunc="median",
                             stdfunc="mad_std", axis=0, masked=True)
        return clipped.mean(axis=0).filled(np.nan)


def fill_holes(image: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Fill each connected hole from a 2-pixel ring around it.

    A ring whose median is BRIGHT_RING_SIGMA robust sigmas above the image median belongs to a
    saturated core, which becomes a solid plateau at the ring's maximum; any other hole (a
    bad-pixel cluster on empty sky) takes the ring's median, about the local sky. (The image
    maximum used before turned a fixed bad-pixel cluster into a bright fake star; the ring
    maximum still left it a 3-sigma bump.) Returns a new array.
    """
    labels, _ = ndimage.label(hole)
    out = image.copy()
    ny, nx = image.shape
    sky = float(np.nanmedian(image)) if np.isfinite(image).any() else 0.0
    bright = sky + BRIGHT_RING_SIGMA * robust_sigma(image)
    for k, box in enumerate(ndimage.find_objects(labels), start=1):
        sl = (slice(max(box[0].start - 2, 0), min(box[0].stop + 2, ny)),
              slice(max(box[1].start - 2, 0), min(box[1].stop + 2, nx)))
        blob = labels[sl] == k
        sub = image[sl]
        ring = ndimage.binary_dilation(blob, iterations=2) & ~blob & np.isfinite(sub)
        if ring.any():
            level = np.median(sub[ring])
            out[sl][blob] = np.max(sub[ring]) if level > bright else level
    return out.astype(np.float32)


def combine(layers: Sequence[np.ndarray], covers: Sequence[np.ndarray]) -> Combined | None:
    """Combine same-shape layers (NaN = flagged) with their coverage masks. None if all bad."""
    kept = reject_noisy(layers)
    if not kept:
        return None
    cube = np.stack([layers[i] for i in kept]).astype(np.float32)
    cover = np.stack([covers[i] for i in kept])
    n_cover = cover.sum(axis=0)
    n_nan = (cover & ~np.isfinite(cube)).sum(axis=0)
    image = clipped_mean(cube).astype(np.float32)
    covered = n_cover > 0
    # Fill only where enough frames agree; in a thin visit a flagged cluster stays NaN.
    hole = (n_cover >= MIN_FRAMES_TO_CLIP) & ~np.isfinite(image)
    if hole.any() and np.isfinite(image).any():
        image = fill_holes(image, hole)
    flag_fraction = float(n_nan.sum() / n_cover.sum()) if n_cover.sum() else 0.0
    return Combined(image=np.where(covered, image, np.nan).astype(np.float32), kept=tuple(kept),
                    flag_fraction=flag_fraction,
                    saturated=covered & (n_nan >= SATURATED_SHARE * n_cover),
                    covered=covered)
