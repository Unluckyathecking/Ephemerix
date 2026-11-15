"""Molecular band depths measured against a local continuum.

Units: wavelengths in micrometres, fluxes in mJy (F_nu). A band depth is
D = 1 - F_band / F_cont, where F_band is the weighted mean flux in the band window and
F_cont is the continuum interpolated in log flux versus log wavelength between the
weighted means of two flanking windows. A power-law continuum gives D = 0 exactly,
and a blackbody or reddened star (concave in log-log) gives D <= 0, so a smooth source
cannot fake an absorption band; a star plus rising dust (convex) can give a shallow
positive D, which is why a band also has to reach half the template's own depth.

Written with Claude Code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# name, band window, blue continuum window, red continuum window (um). The windows are
# wide enough that a sparse spectrum (about 25 points over 1-5 um) still has a point in
# most of them; the template's reference depth is measured on the same windows.
BANDS: tuple[tuple[str, tuple[float, float], tuple[float, float], tuple[float, float]], ...] = (
    ("H2O 1.4 um", (1.32, 1.50), (1.05, 1.30), (1.50, 1.75)),
    ("H2O 1.9 um", (1.80, 2.02), (1.50, 1.75), (2.02, 2.30)),
    ("H2O 2.7 um", (2.50, 3.00), (2.02, 2.40), (3.70, 4.15)),
    ("CH4 3.3 um", (3.10, 3.55), (2.02, 2.40), (3.70, 4.15)),
    ("CO2 4.3 um", (4.20, 4.36), (3.90, 4.18), (4.36, 4.50)),
    ("CO 4.6 um", (4.50, 4.80), (4.36, 4.50), (4.82, 4.97)),
)
MIN_TEMPLATE_DEPTH = 0.2  # a band is "expected" when the best template is at least this deep
DETECT_SIGMA = 3.0  # depth must exceed this many sigma ...
DETECT_FRACTION = 0.5  # ... and this fraction of the template's depth
MIN_WINDOW_SNR = 3.0  # continuum windows need this S/N for the depth to be measured


@dataclass(frozen=True)
class Band:
    """One band measured on the data and on the best template, at the data wavelengths."""

    name: str
    depth: float | None  # measured on the data; None if not measurable
    err: float | None
    template_depth: float | None
    expected: bool
    detected: bool


def _window_mean(wl, f, sig, lo_hi) -> tuple[float, float, float] | None:
    """(weighted mean flux, its error, mean wavelength) in a window, or None if empty."""
    inside = (wl >= lo_hi[0]) & (wl <= lo_hi[1])
    if not inside.any():
        return None
    w = 1.0 / sig[inside] ** 2
    return (float(np.sum(w * f[inside]) / w.sum()), float(1.0 / np.sqrt(w.sum())),
            float(np.sum(w * wl[inside]) / w.sum()))


def band_depth(wl: np.ndarray, f: np.ndarray, sig: np.ndarray, band, blue, red,
               min_snr: float = MIN_WINDOW_SNR) -> tuple[float, float] | None:
    """(depth, 1-sigma error) of one band, or None if a window is empty or too faint.

    Arrays are wavelength (um), flux and error (same unit). The error is propagated to
    first order from the three window means.
    """
    parts = [_window_mean(wl, f, sig, win) for win in (band, blue, red)]
    if any(p is None for p in parts):
        return None
    (fb, eb, lb), (f1, e1, l1), (f2, e2, l2) = parts
    if f1 <= min_snr * e1 or f2 <= min_snr * e2:
        return None
    t = (np.log(lb) - np.log(l1)) / (np.log(l2) - np.log(l1))
    cont = float(np.exp((1 - t) * np.log(f1) + t * np.log(f2)))
    ratio = fb / cont
    err = float(np.hypot(eb / cont, abs(ratio) * np.hypot((1 - t) * e1 / f1, t * e2 / f2)))
    return 1.0 - ratio, err


def measure_bands(wl: np.ndarray, f: np.ndarray, sig: np.ndarray,
                  template_fnu: np.ndarray) -> list[Band]:
    """Every band in BANDS on the data and on the best template (same wavelengths).

    sig should already include any rescaling of the errors. A band is expected when the
    template is at least MIN_TEMPLATE_DEPTH deep there; it is detected when the data's
    depth is at least DETECT_SIGMA sigma and DETECT_FRACTION of the template's depth.
    """
    out = []
    # A template scaled to zero (no positive scale fits) has no depths; `or 1.0` keeps its
    # errors non-zero so band_depth returns None rather than dividing by zero.
    tsig = np.full(wl.shape, 1e-6) * (np.max(np.abs(template_fnu)) or 1.0)
    for name, band, blue, red in BANDS:
        tm = band_depth(wl, template_fnu, tsig, band, blue, red, min_snr=0.0)
        dm = band_depth(wl, f, sig, band, blue, red)
        tdepth = None if tm is None else tm[0]
        expected = tdepth is not None and tdepth >= MIN_TEMPLATE_DEPTH
        detected = bool(expected and dm is not None and dm[0] >= DETECT_SIGMA * dm[1]
                        and dm[0] >= DETECT_FRACTION * tdepth)
        out.append(Band(name, None if dm is None else dm[0], None if dm is None else dm[1],
                        tdepth, expected, detected))
    return out
