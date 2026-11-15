"""Vectorised least-squares fits of many model shapes to one spectrum.

Every fit minimises chi2 = sum(w (d - model)^2), w = 1 / sigma^2, with non-negative
scale factors. Shapes are rows of a matrix sampled at the data wavelengths; data and
models share one unit (mJy). Inputs are never modified.

Written with Claude Code.
"""

from __future__ import annotations

import numpy as np


def fit_one(shapes: np.ndarray, d: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best non-negative scale and chi2 for each row of shapes (m x n) against data d (n).

    Returns (scales, chi2), each of length m.
    """
    den = (shapes * shapes) @ w
    num = (shapes * w) @ d
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(den > 0, num / den, 0.0)
    s = np.clip(s, 0.0, None)
    chi2 = ((d - s[:, None] * shapes) ** 2) @ w
    return s, chi2


def fit_two(a: np.ndarray, b: np.ndarray, d: np.ndarray,
            w: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Non-negative least squares of d against two components a_i, b_i (rows, m x n) per row.

    Solves the 2x2 normal equations; where a scale comes out negative, the better of the
    two one-component fits is taken instead (the exact NNLS solution for two columns).
    Returns (scale_a, scale_b, chi2), each of length m.
    """
    aa, bb, ab = (a * a) @ w, (b * b) @ w, (a * b) @ w
    ad, bd = (a * w) @ d, (b * w) @ d
    dd = float(np.sum(w * d * d))
    det = aa * bb - ab * ab
    with np.errstate(divide="ignore", invalid="ignore"):
        sa = np.where(det > 0, (ad * bb - bd * ab) / det, -1.0)
        sb = np.where(det > 0, (bd * aa - ad * ab) / det, -1.0)
    both = (sa >= 0) & (sb >= 0)
    chi_both = dd - 2 * (sa * ad + sb * bd) + sa * sa * aa + 2 * sa * sb * ab + sb * sb * bb
    sa1, chi_a = fit_one(a, d, w)
    sb1, chi_b = fit_one(b, d, w)
    use_a = chi_a <= chi_b
    sa_out = np.where(both, sa, np.where(use_a, sa1, 0.0))
    sb_out = np.where(both, sb, np.where(use_a, 0.0, sb1))
    chi = np.where(both, chi_both, np.minimum(chi_a, chi_b))
    return sa_out, sb_out, np.maximum(chi, 0.0)


def worst_points(resid_z: np.ndarray, n_drop: int) -> np.ndarray:
    """Boolean mask, True for points kept, dropping the n_drop largest |normalised residuals|."""
    keep = np.ones(resid_z.shape, dtype=bool)
    if n_drop > 0:
        keep[np.argsort(np.abs(resid_z))[-n_drop:]] = False
    return keep


def noise_scale(resid_z: np.ndarray) -> float:
    """Robust white-noise scale of normalised residuals ordered by wavelength (dimensionless).

    Uses differences of neighbouring residuals, so a misfit that varies slowly with
    wavelength cancels: 1.4826 * MAD(r_i - r_{i-1}) / sqrt(2). Smooth correlated noise
    (for example a blended background source) also cancels and is not measured here.
    """
    if resid_z.size < 4:
        return 1.0
    diff = np.diff(resid_z)
    return float(1.4826 * np.median(np.abs(diff - np.median(diff))) / np.sqrt(2.0))
