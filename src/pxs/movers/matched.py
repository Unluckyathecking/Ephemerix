"""Per-frame matched-filter planes (KBMOD's psi and phi) with empirical noise normalisation.

For a source of flux A x template_i in frame i with PSF P_i, the likelihood is maximised by
psi_i = template_i x (D_i / V_i) (*) P_i and phi_i = template_i^2 x (1 / V_i) (*) P_i^2
((*) is correlation). Along a trajectory, A = sum psi / sum phi and S/N = sum psi / sqrt(sum
phi). The pipeline variance is about 1.5x too small and resampling correlates neighbouring
pixels, so each frame's variance is rescaled by s^2 until its single-frame S/N map,
psi / sqrt(phi), has unit robust scatter (psi / s^2, phi / s^2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve

from pxs.spherex import config

from .difference import Cube

H_NU_OVER_K = 14387.77  # um K


def reflected_template(wave_um: np.ndarray, ref_um: float = 1.0) -> np.ndarray:
    """Sunlight reflected at constant albedo: F_nu of a 5778 K blackbody, 1 at ref_um."""
    def bnu(w: np.ndarray) -> np.ndarray:
        return (1.0 / w) ** 3 / np.expm1(H_NU_OVER_K / (np.asarray(w, float) * 5778.0))
    return bnu(np.asarray(wave_um, float)) / bnu(np.array(ref_um))


def flat_template(wave_um: np.ndarray) -> np.ndarray:
    """Constant F_nu (used for the thermal search, one detector band only)."""
    return np.ones_like(np.asarray(wave_um, float))


@dataclass(frozen=True)
class Planes:
    """psi, phi: (n, H, W) float32 with 0 where there is no data. noise_scale: (n,) the s
    each frame was normalised by. Flux of a fit, in mJy at the template's reference
    wavelength, is sum(psi) / sum(phi) x MJYSR_TO_MJY."""

    psi: np.ndarray
    phi: np.ndarray
    noise_scale: np.ndarray

    @property
    def n(self) -> int:
        return int(self.psi.shape[0])


def _correlate(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    return fftconvolve(img, kernel[::-1, ::-1], mode="same")


def robust_sigma(a: np.ndarray) -> float:
    v = a[np.isfinite(a)]
    if v.size < 10:
        return math.nan
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def frame_planes(diff: np.ndarray, var: np.ndarray, psf: np.ndarray,
                 tmpl: float) -> tuple[np.ndarray, np.ndarray, float]:
    """(psi, phi, s) of one frame."""
    ok = np.isfinite(diff) & np.isfinite(var) & (var > 0)
    inv = np.where(ok, 1.0 / np.where(ok, var, 1.0), 0.0)
    psi = tmpl * _correlate(np.where(ok, diff, 0.0) * inv, psf)
    phi = tmpl * tmpl * _correlate(inv, psf * psf)
    # Only pixels whose PSF footprint is mostly good are kept.
    cover = _correlate(ok.astype(float), psf) / max(float(psf.sum()), 1e-12)
    keep = (cover > 0.7) & (phi > 0)
    psi, phi = np.where(keep, psi, 0.0), np.where(keep, phi, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        snr = np.where(keep, psi / np.sqrt(phi), np.nan)
    s = robust_sigma(snr)
    if not math.isfinite(s) or s <= 0:
        return np.zeros_like(psi, np.float32), np.zeros_like(phi, np.float32), math.nan
    # Equivalent to V -> s^2 V: the flux sum(psi)/sum(phi) is unchanged, S/N drops by s.
    return (psi / s ** 2).astype(np.float32), (phi / s ** 2).astype(np.float32), s


def planes(cube: Cube) -> Planes:
    """Matched-filter planes for every frame of a difference cube."""
    out = [frame_planes(cube.diff[i], cube.var[i], cube.psf[i], float(cube.template[i]))
           for i in range(len(cube))]
    return Planes(np.stack([o[0] for o in out]), np.stack([o[1] for o in out]),
                  np.array([o[2] for o in out]))


def flux_mjy(sum_psi: np.ndarray, sum_phi: np.ndarray) -> np.ndarray:
    """Fitted flux (mJy at the template reference wavelength) from trajectory sums."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(sum_phi > 0, sum_psi / sum_phi, np.nan) * config.MJYSR_TO_MJY
