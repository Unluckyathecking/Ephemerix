"""Bin the CALSPEC solar model (sun_mod_001.fits) to R = 1000 over 0.70-5.10 um as F_nu.

Source: https://archive.stsci.edu/hlsps/reference-atlases/cdbs/current_calspec/sun_mod_001.fits
(Kurucz special solar model, T/g = 5777/4.4, R = 5000, normalised to observation at
0.68-0.77 um by R. Bohlin; CALSPEC, Bohlin, Gordon & Tremblay 2014, PASP 126, 711).
Also prints how far the observed CALSPEC solar spectrum (sun_reference_stis_002.fits)
and a 5777 K blackbody are from the model in SPHEREx-like R = 40 bins.

    uv run python probes/solarsystem/make_solar_table.py <dir with the two fits files>
"""
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

d = Path(sys.argv[1])
out = Path(__file__).resolve().parents[2] / "src/pxs/solarsystem/solar_ref.csv"
C = 2.99792458e18  # A/s


def fnu(path):
    t = fits.open(path)[1].data
    w = np.asarray(t["WAVELENGTH"], float)
    f = np.asarray(t["FLUX"], float)
    return w / 1e4, f * w**2 / C  # um, erg/s/cm2/Hz


def binned(wl, f, edges):
    idx = np.searchsorted(edges, wl) - 1
    ok = (idx >= 0) & (idx < len(edges) - 1)
    s = np.bincount(idx[ok], f[ok], len(edges) - 1)
    n = np.bincount(idx[ok], None, len(edges) - 1)
    return s / np.where(n > 0, n, np.nan)


wl, f = fnu(d / "sun_mod_001.fits")
edges = 0.70 * (1 + 1 / 1000) ** np.arange(0, 2000)
edges = edges[edges <= 5.105]
mid = np.sqrt(edges[:-1] * edges[1:])
fb = binned(wl, f, edges)
assert np.all(np.isfinite(fb)), "empty bins: model sampling coarser than R=1000"
norm = np.interp(1.25, mid, fb)
lines = ["# CALSPEC sun_mod_001 (Kurucz solar model, Bohlin), F_nu binned to R=1000,",
         "# normalised to 1 at 1.25 um. Columns: wavelength um (vacuum), relative F_nu.",
         "wl_um,fnu_rel"]
lines += [f"{w:.6f},{v / norm:.6e}" for w, v in zip(mid, fb)]
out.write_text("\n".join(lines) + "\n")
print(f"wrote {out} ({len(mid)} rows)")

# Comparisons on R = 40 bins
e40 = 0.75 * (1 + 1 / 40) ** np.arange(0, 120)
e40 = e40[e40 <= 5.0]
m40 = np.sqrt(e40[:-1] * e40[1:])
mod40 = binned(wl, f, e40)
ws, fs = fnu(d / "sun_reference_stis_002.fits")
obs40 = binned(ws, fs, e40)
ok = np.isfinite(obs40)
r = obs40[ok] / mod40[ok]
print(f"observed/model at R=40, 0.75-{m40[ok].max():.2f} um: {r.min():.3f}-{r.max():.3f}, "
      f"rms dev {np.std(r / np.median(r)):.3%}")
h, k = 6.62607015e-27, 1.380649e-16
nu = 2.99792458e14 / m40
bb = nu**3 / np.expm1(h * nu / (k * 5777.0))
q = mod40 / bb
q /= np.interp(1.25, m40, q)
print(f"model/blackbody(5777 K), normalised at 1.25 um: min {q.min():.3f} at {m40[q.argmin()]:.2f} um,"
      f" max {q.max():.3f} at {m40[q.argmax()]:.2f} um")
for w in (0.8, 1.0, 1.5, 2.0, 2.5, 3.3, 4.0, 4.5, 5.0):
    print(f"  {w} um: model/BB = {np.interp(w, m40, q):.3f}")
