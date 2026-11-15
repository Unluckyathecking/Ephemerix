"""Stack -> 8-bit greyscale PNG with one shared asinh stretch per (mission, band).

Each frame has its own background (sigma-clipped median) removed, because the sky level
differs between epochs. The black point, softening and white point are then set once
for the whole frame set, in units of the typical per-frame noise, so a source of a
given brightness looks the same in every epoch. Bright is white on a dark sky. Pixels
with no data (NaN) are drawn at the background level, not black. No smoothing.

A saturated core (`saturated_cores`: the stack's saturated mask, a hole of no-data pixels
enclosed by data, or a dark pit inside a source the stack calls saturated; at least
MIN_CORE_PX pixels; ringed by pixels at least BRIGHT_RING_SIGMA noise above the background or
among the brightest BRIGHT_RING_PERCENTILE of the frame) is drawn at full white, and its
pixels are left out of the white-point percentile, so the fill value of a saturated star never
sets the stretch. A flagged cluster on faint sky is not a core: it keeps the background
rendering. A smaller hole inside the data (a few bad pixels) takes the mean of its neighbours.

Every other pixel of the saturated mask (flagged in most exposures) is a display gap: its value is
a fill or comes from the one or two exposures that were not flagged, often far below the truth,
which drew as black squares and crosses inside a bright star's glare (Betelgeuse in W2). Gaps are
closed over by GAP_CLOSE_PX and hole-filled, and each connected gap is drawn at the median of the
data in a RING_PX ring around it, so the image reads as sky with a few even patches.
`no_data_mask` (NaN plus the gaps, cores included) is what `no_data_fraction` counts and
`write_gaps_png` saves for the page. Display only: photometry and centroids never read these.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.stats import sigma_clipped_stats
from PIL import Image
from scipy import ndimage

from pxs.grid import Stack

BLACK_SIGMA = 2.0  # black point, noise units below the background
SOFT_SIGMA = 2.0  # asinh softening, noise units: linear below, logarithmic above
WHITE_PERCENTILE = 99.8  # white point, percentile of all background-subtracted pixels
MIN_WHITE_SIGMA = 20.0  # never stretch noise to full white
THUMB_PX = 160
BRIGHT_RING_SIGMA = 10.0  # a core's surrounding ring must be this far above the background
BRIGHT_RING_PERCENTILE = 95.0  # or the ring is this bright for the frame (a halo-filled frame)
RING_PX = 3  # width of that ring, grid pixels
MIN_CORE_PX = 9  # smaller holes are bad pixels, not a saturated core
CRATER_LEVELS = tuple(np.arange(1, 19) / 20.0)  # fractions of a source's peak, see `_craters`
HOLE_SMOOTH_PX = 1.5  # small holes inside the data take a local mean of this Gaussian width
GAP_CLOSE_PX = 2  # flagged pixels this close together form one gap (specks between them join)


@dataclass(frozen=True)
class FrameLevels:
    """Background and noise of one frame, in the Stack's image unit."""

    background: float
    noise: float


@dataclass(frozen=True)
class Stretch:
    """A shared asinh stretch in units of the image (background-subtracted)."""

    black: float
    soft: float
    white: float

    def apply(self, x: np.ndarray) -> np.ndarray:
        """Map background-subtracted values to [0, 1]."""
        top = np.arcsinh((self.white - self.black) / self.soft)
        v = np.arcsinh((x - self.black) / self.soft) / top
        return np.clip(v, 0.0, 1.0)


def frame_levels(image: np.ndarray) -> FrameLevels:
    """Sigma-clipped median and standard deviation of the finite pixels (3 sigma, 5 iterations)."""
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return FrameLevels(0.0, 1.0)
    _, median, std = sigma_clipped_stats(finite, sigma=3.0, maxiters=5)
    noise = float(std) if np.isfinite(std) and std > 0 else 1.0
    return FrameLevels(float(median), noise)


def _enclosed_nan(image: np.ndarray) -> np.ndarray:
    """NaN pixels whose NaN region does not touch the image border (holes inside the data)."""
    nan = ~np.isfinite(image)
    labels, _ = ndimage.label(nan)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return nan & ~np.isin(labels, border[border > 0])


def _bright_ringed(blobs: np.ndarray, image: np.ndarray, lv: FrameLevels) -> np.ndarray:
    """The connected blobs whose ring median is at least BRIGHT_RING_SIGMA noise above sky."""
    labels, n = ndimage.label(blobs)
    keep = np.zeros(n + 1, bool)
    finite = np.isfinite(image)
    top = float(np.percentile(image[finite], BRIGHT_RING_PERCENTILE)) if finite.any() else np.inf
    for k, box in enumerate(ndimage.find_objects(labels), start=1):
        sl = tuple(slice(max(b.start - RING_PX, 0), b.stop + RING_PX) for b in box)
        blob = labels[sl] == k
        ring = ndimage.binary_dilation(blob, iterations=RING_PX) & ~blobs[sl] & finite[sl]
        if ring.any() and blob.sum() >= MIN_CORE_PX:
            level = float(np.median(image[sl][ring]))
            keep[k] = level - lv.background >= BRIGHT_RING_SIGMA * lv.noise or level >= top
    return keep[labels]


def _fill_small_holes(x: np.ndarray, holes: np.ndarray) -> np.ndarray:
    """Holes inside the data that are not saturated cores (a few bad pixels, often inside a
    bright star) take the local mean of their neighbours instead of the background, so they
    do not show as dark pits. Returns a new array."""
    if not holes.any():
        return x
    good = (~holes).astype(float)
    num = ndimage.gaussian_filter(np.where(holes, 0.0, x), HOLE_SMOOTH_PX)
    den = ndimage.gaussian_filter(good, HOLE_SMOOTH_PX)
    with np.errstate(invalid="ignore", divide="ignore"):
        local = np.where(den > 1e-3, num / den, 0.0)
    return np.where(holes, local, x)


def _craters(image: np.ndarray, lv: FrameLevels) -> np.ndarray:
    """Dips inside bright sources: pixels below CRATER_LEVELS of the source's peak that are
    enclosed by pixels above it. An unsaturated PSF falls off monotonically and has none; a
    SPHEREx core that saturated in most exposures stacks to a dark pit with valid-looking
    values (RW Aur), which is what this finds."""
    x = np.where(np.isfinite(image), image - lv.background, 0.0)
    labels, _ = ndimage.label(x > BRIGHT_RING_SIGMA * lv.noise)
    out = np.zeros(image.shape, bool)
    for k, box in enumerate(ndimage.find_objects(labels), start=1):
        sub = np.where(labels[box] == k, x[box], 0.0)
        for f in CRATER_LEVELS:
            above = sub > f * sub.max()
            out[box] |= ndimage.binary_fill_holes(above) & ~above
    return out


def saturated_cores(stack: Stack) -> np.ndarray:
    """Bool mask of saturated cores: the stack's saturated mask, enclosed no-data holes and,
    when the stack says "saturated", dark pits inside bright sources (`_craters`), closed and
    hole-filled, kept only where ringed by bright pixels (see module docstring)."""
    image = stack.image
    cand = _enclosed_nan(image)
    if "saturated" in stack.warnings:
        cand = cand | _craters(image, frame_levels(image))
    if stack.saturated_mask is not None:
        cand = cand | stack.saturated_mask
    if not cand.any():
        return cand
    cand = ndimage.binary_fill_holes(ndimage.binary_closing(cand, iterations=2) | cand)
    return _bright_ringed(cand, image, frame_levels(image))


def _flagged_gaps(stack: Stack) -> np.ndarray:
    """The saturated mask closed over GAP_CLOSE_PX and hole-filled (see module docstring)."""
    mask = stack.saturated_mask
    if mask is None or not mask.any():
        return np.zeros(stack.image.shape, bool)
    return ndimage.binary_fill_holes(ndimage.binary_closing(mask, iterations=GAP_CLOSE_PX) | mask)


def no_data_mask(stack: Stack) -> np.ndarray:
    """Pixels with no usable measurement: NaN, or inside a flagged gap (saturated cores too)."""
    return ~np.isfinite(stack.image) | _flagged_gaps(stack)


def no_data_fraction(stack: Stack) -> float:
    """Share of the frame's pixels in `no_data_mask`."""
    return float(no_data_mask(stack).mean())


def _fill_gaps(x: np.ndarray, gaps: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Each connected gap takes the median of the valid pixels in a RING_PX ring around it (the
    frame median when there are none). Returns a new array."""
    if not gaps.any():
        return x
    out = x.copy()
    labels, _ = ndimage.label(gaps)
    fallback = float(np.median(x[valid])) if valid.any() else 0.0
    for k, box in enumerate(ndimage.find_objects(labels), start=1):
        sl = tuple(slice(max(b.start - RING_PX, 0), b.stop + RING_PX) for b in box)
        blob = labels[sl] == k
        ring = ndimage.binary_dilation(blob, iterations=RING_PX) & ~gaps[sl] & valid[sl]
        out[sl][blob] = float(np.median(x[sl][ring])) if ring.any() else fallback
    return out


def shared_stretch(stacks: Sequence[Stack]) -> Stretch:
    """One stretch for a set of frames of the same (mission, band). Saturated cores are left
    out of the white-point percentile."""
    levels = [frame_levels(s.image) for s in stacks]
    noise = float(np.median([lv.noise for lv in levels])) if levels else 1.0
    resid = [
        (s.image - lv.background)[np.isfinite(s.image) & ~saturated_cores(s)]
        for s, lv in zip(stacks, levels)
    ]
    pool = np.concatenate(resid) if resid else np.zeros(1)
    white = float(np.percentile(pool, WHITE_PERCENTILE)) if pool.size else 0.0
    white = max(white, MIN_WHITE_SIGMA * noise)
    return Stretch(black=-BLACK_SIGMA * noise, soft=SOFT_SIGMA * noise, white=white)


def to_uint8(stack: Stack, stretch: Stretch) -> np.ndarray:
    """8-bit display image (row 0 north). Saturated cores are white; flagged gaps take the
    level around them; other NaN pixels get the frame's background level."""
    lv = frame_levels(stack.image)
    finite = np.isfinite(stack.image)
    x = np.where(finite, stack.image - lv.background, 0.0)
    cores = saturated_cores(stack)
    x = _fill_small_holes(x, _enclosed_nan(stack.image) & ~cores)
    gaps = _flagged_gaps(stack) & ~cores
    x = _fill_gaps(x, gaps, finite & ~gaps & ~cores)
    v = np.where(cores, 1.0, stretch.apply(x))
    return np.round(v * 255.0).astype(np.uint8)


def write_png(stack: Stack, stretch: Stretch, path: Path) -> Path:
    """Write the frame as a greyscale PNG. Deterministic: no metadata, fixed compression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(to_uint8(stack, stretch), mode="L").save(path, format="PNG", optimize=False)
    return path


def write_gaps_png(stack: Stack, path: Path) -> Path:
    """Write `no_data_mask` as a greyscale PNG: 255 where there is no data, 0 elsewhere."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mask = (no_data_mask(stack) * 255).astype(np.uint8)
    Image.fromarray(mask, mode="L").save(path, format="PNG", optimize=False)
    return path


def write_thumb(stack: Stack, stretch: Stretch, path: Path, size_px: int = THUMB_PX) -> Path:
    """Square gallery thumbnail of a frame, box-resampled to size_px."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(to_uint8(stack, stretch), mode="L")
    img.resize((size_px, size_px), Image.Resampling.BOX).save(path, format="PNG")
    return path
