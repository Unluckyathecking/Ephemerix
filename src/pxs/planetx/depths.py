"""5-sigma point-source depths, AB mag, as (shallow, deep) ranges.

Literature:
- SPHEREx per spectral channel after four all-sky maps (two years), in flight: 19.5-19.9 AB at
  0.75-3.8 um and 17.8-18.8 AB at 3.8-5.0 um (Bock et al. 2025, "The SPHEREx Satellite
  Mission", arXiv:2511.02985, abstract and Fig. 5). Which value belongs to which detector is
  not split out, so each detector band gets the whole range.
- Single all-sky map: one quarter of the exposure, so 2.5 log10(sqrt 4) = 0.75 mag shallower,
  assuming white noise. Derived here, not published. A planet moves 7-23 arcmin between maps,
  so only this depth applies to a blind search; the four-map depth needs shift-and-stack
  along an assumed orbit.
- Detector band: averaging the ~17 channels of one detector gains 2.5 log10(sqrt 17) =
  1.54 mag for a flat spectrum. Derived; it also needs the frames, taken over days, to be
  stacked on the moving planet.
- WISE: W1 > 16.7 Vega (19.40 AB), 90% completeness, the WISE+NEOWISE 3pi Planet Nine search
  (Meisner et al. 2018, AJ 155, 166); 0.08 and 0.11 mJy (19.14 and 18.80 AB) stationary-source
  5-sigma (Wright et al. 2010, AJ 140, 1868); W2 15.6 Vega (18.94 AB) as quoted by Linder &
  Mordasini 2016.

Measured: forced-photometry errors per SPHEREx frame (one channel) in our gallery
manifests. These are formal (VARIANCE) errors; empty apertures give
noise 2-4x larger, i.e. 0.75-1.5 mag shallower.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from .photometry import CHANNELS_PER_SPHEREX_BAND, SPHEREX_BANDS, WISE_BANDS, ab_mag

FOUR_MAP_CHANNEL = {1: (19.5, 19.9), 2: (19.5, 19.9), 3: (19.5, 19.9), 4: (19.5, 19.9),
                    5: (17.8, 18.8), 6: (17.8, 18.8)}
ONE_MAP_PENALTY = 2.5 * math.log10(math.sqrt(4))
BAND_GAIN = 2.5 * math.log10(math.sqrt(CHANNELS_PER_SPHEREX_BAND))
WISE_DEPTH = {"WISE W1": (19.14, 19.40), "WISE W2": (18.80, 18.94)}
SNR_BRIGHT = 5.0  # points detected above this are source-noise dominated; left out


@dataclass(frozen=True)
class Depth:
    key: str
    label: str
    kind: str  # "literature", "derived" or "measured"
    per: str  # "channel" or "band": compare with a channel flux or a band-mean flux
    ab: dict[str, tuple[float, float]]  # band name -> (shallow, deep)
    note: str


def _spx(f) -> dict[str, tuple[float, float]]:
    return {b.name: f(FOUR_MAP_CHANNEL[i + 1]) for i, b in enumerate(SPHEREX_BANDS)}


def literature_depths() -> list[Depth]:
    pen, gain = ONE_MAP_PENALTY, BAND_GAIN
    return [
        Depth("spx_one_map_channel", "SPHEREx, one all-sky map, per channel", "derived", "channel",
              _spx(lambda r: (r[0] - pen, r[1] - pen)),
              "Bock et al. 2025 four-map depth made 0.75 mag shallower for one map."),
        Depth("spx_one_map_band", "SPHEREx, one all-sky map, 17 channels combined", "derived",
              "band", _spx(lambda r: (r[0] - pen + gain, r[1] - pen + gain)),
              "As above, plus 1.54 mag for averaging one detector's ~17 channels."),
        Depth("spx_four_map_channel", "SPHEREx, four maps (2 yr), per channel", "literature",
              "channel", _spx(lambda r: r),
              "Bock et al. 2025. Reachable only by stacking along an assumed orbit."),
        Depth("wise", "WISE / NEOWISE", "literature", "band", dict(WISE_DEPTH),
              "W1: Wright et al. 2010 and Meisner et al. 2018; W2: Wright et al. 2010 and "
              "Linder & Mordasini 2016."),
    ]


def measured_channel_depth(manifests: Iterable[dict]) -> Depth:
    """Per-frame 5-sigma depth per detector from manifest spectra: (median err, 25th pct err).

    Uses single-pass spectra only, unflagged points with |flux / err| < 5.
    """
    errs: dict[int, list[float]] = {}
    for m in manifests:
        for spec in m.get("spectra", []):
            if spec.get("id") == "spx-all" or spec.get("unit") != "mJy":
                continue
            for p in spec["points"]:
                e, f, d = p.get("err"), p.get("flux"), p.get("detector")
                if p.get("flagged") or not e or f is None or d not in FOUR_MAP_CHANNEL:
                    continue
                if abs(f / e) < SNR_BRIGHT:
                    errs.setdefault(d, []).append(e * 1000.0)  # mJy -> uJy
    ab = {}
    for i, b in enumerate(SPHEREX_BANDS):
        e = sorted(errs.get(i + 1, []))
        if len(e) >= 10:
            ab[b.name] = (round(ab_mag(5 * statistics.median(e)), 2),
                          round(ab_mag(5 * e[len(e) // 4]), 2))
    return Depth("spx_measured_channel", "SPHEREx frames in our gallery views (measured, formal errors)",
                 "measured", "channel", ab,
                 "Median and 25th-percentile per-frame errors in the gallery manifests; "
                 "empty-aperture noise is 2-4x larger (0.75-1.5 mag shallower).")


WISE_NAMES = tuple(b.name for b in WISE_BANDS)
