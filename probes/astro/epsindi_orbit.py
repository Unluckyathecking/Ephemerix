"""Epsilon Indi Ba/Bb: is the 16-year W2 motion biased, or is Gaia DR3 the wrong reference?

    uv run python probes/astro/epsindi_orbit.py web/gallery/epsilon-indi-b/manifest.json

1. Refits the published W2 centroids and compares the motion with Gaia DR3 (a 34-month
   single-star fit to the unresolved pair, RUWE 4.30) and with the barycentre motion of Chen
   et al. 2022 (AJ 163, 288, arXiv:2205.08077, Table 4: +3987.41 +- 0.12, -2505.35 +- 0.10
   mas/yr, from 88 VLT/FORS2 epochs 2005-2016 and the relative orbit).
2. Looks for an 11-year term in the residuals.
3. Photocentre orbit from Chen's elements (P 11.0197 yr, a 661.58 mas, e 0.54042, i 77.082,
   Omega 147.959, omega 328.27 deg, Mbb/Mtot 0.4431). The photocentre sits (beta - 0.4431) a
   from the barycentre, beta being Bb's share of the light: about 0.17-0.21 in the far red
   (I: 17.15 and 18.91; z flux ratio 0.259, King et al. 2010 via Dieterich et al. 2018), so
   160-180 mas for Gaia. Table 4 has no time of periastron, so it is scanned over one period:
   the range of the proper-motion offset a straight-line fit picks up over Gaia DR3's window
   and over our W2 epochs. The W2 share (0.3-0.5) is an assumption from typical T1 and T6
   brightness at 4.6 um, not a measured value.

Written with Claude Code.
"""

import json
import sys
from pathlib import Path

import numpy as np

from pxs.astrometry import _tangent_offsets, fit_motion, parallax_factors, px_to_sky

GAIA = (3981.977, -2466.832)
CHEN = (3987.41, -2505.35)
P, A_MAS, ECC, INC, BIGOM, OM = 11.0197, 661.58, 0.54042, 77.082, 147.959, 328.27
MASS_FRAC_BB = 0.4431


def orbit_bb_rel(tyr, t0):
    """Bb relative to Ba (east, north) in mas at years `tyr`, periastron at `t0`."""
    mean = 2 * np.pi * (tyr - t0) / P
    ecc_anom = mean.copy()
    for _ in range(60):
        ecc_anom = ecc_anom - (ecc_anom - ECC * np.sin(ecc_anom) - mean) / (1 - ECC * np.cos(ecc_anom))
    xo, yo = A_MAS * (np.cos(ecc_anom) - ECC), A_MAS * np.sqrt(1 - ECC**2) * np.sin(ecc_anom)
    w, node, i = np.radians(OM), np.radians(BIGOM), np.radians(INC)
    a = np.cos(w) * np.cos(node) - np.sin(w) * np.sin(node) * np.cos(i)
    b = np.cos(w) * np.sin(node) + np.sin(w) * np.cos(node) * np.cos(i)
    f = -np.sin(w) * np.cos(node) - np.cos(w) * np.sin(node) * np.cos(i)
    g = -np.sin(w) * np.sin(node) + np.cos(w) * np.cos(node) * np.cos(i)
    return b * xo + g * yo, a * xo + f * yo


def pm_offset(tyr, beta, t0):
    """Slope (mas/yr east, north) a straight-line fit gives the photocentre's orbital term."""
    e, n = orbit_bb_rel(tyr, t0)
    k = beta - MASS_FRAC_BB
    return np.polyfit(tyr, k * e, 1)[0], np.polyfit(tyr, k * n, 1)[0]


def w2_epochs(m):
    fr = [f for f in m["frames"] if f["mission"] == "WISE" and f["band"] == "W2"
          and f["centroid_px"] is not None]
    ra, dec = px_to_sky([f["centroid_px"][0] for f in fr], [f["centroid_px"][1] for f in fr],
                        m["center"]["ra"], m["center"]["dec"], m["fov_arcsec"], m["size_px"])
    return (np.array([f["mjd"] for f in fr]), ra, dec,
            np.array([f["centroid_err_arcsec"] for f in fr]))


def compare(mjd, ra, dec, err, plx):
    r = fit_motion(mjd, ra, dec, err, parallax_mas=plx)
    print(f"W2 epochs only: ({r['pmra_masyr']}, {r['pmdec_masyr']}) +-{r['err_masyr']} mas/yr, "
          f"n={r['n_detections']}, reduced chi2 {r['reduced_chi2']}")
    for name, ref in (("Gaia DR3", GAIA), ("Chen+22 barycentre", CHEN)):
        d = (r["pmra_masyr"] - ref[0], r["pmdec_masyr"] - ref[1])
        print(f"   minus {name}: ({d[0]:+.1f}, {d[1]:+.1f}) mas/yr = "
              f"({d[0] / r['err_pmra_masyr']:+.2f}, {d[1] / r['err_pmdec_masyr']:+.2f}) sigma")
    half = mjd < np.median(mjd)
    for label, k in (("first half ", half), ("second half", ~half)):
        h = fit_motion(mjd[k], ra[k], dec[k], err[k], parallax_mas=plx)
        print(f"   {label}: ({h['pmra_masyr']}, {h['pmdec_masyr']}) +-{h['err_masyr']}")


def residual_term(mjd, ra, dec, err, plx):
    xi, eta = _tangent_offsets(ra, dec, ra[0], dec[0])
    fra, fdec = parallax_factors(mjd, ra[0], dec[0])
    t = (mjd - mjd.mean()) / 365.25
    design = np.column_stack([np.sin(2 * np.pi * t / P), np.cos(2 * np.pi * t / P)]) / err[:, None]
    for label, v, f in (("east ", xi, fra), ("north", eta, fdec)):
        r = np.degrees(v) * 3600 - plx / 1000 * f
        r = r - np.polyval(np.polyfit(t, r, 1, w=1 / err), t)
        co, *_ = np.linalg.lstsq(design, r / err, rcond=None)
        sd = np.sqrt(np.diag(np.linalg.inv(design.T @ design)))
        print(f"   {label}: residual rms {1e3 * r.std():.0f} mas (stated {1e3 * np.median(err):.0f}); "
              f"{P:.0f}-yr term {1e3 * np.hypot(*co):.0f} +- {1e3 * sd.max():.0f} mas")


def orbit_ranges(years):
    t0s = np.linspace(2000.0, 2000.0 + P, 221)
    windows = (("Gaia DR3 window 2014.56-2017.40, far red", np.linspace(2014.56, 2017.40, 40),
                (0.165, 0.206)), ("our W2 epochs", years, (0.30, 0.38, 0.45, 0.50)))
    for label, tt, betas in windows:
        for beta in betas:
            d = np.array([pm_offset(tt, beta, t0) for t0 in t0s])
            print(f"   {label}, Bb share {beta}: photocentre orbit "
                  f"{abs(beta - MASS_FRAC_BB) * A_MAS:.0f} mas; motion offset east "
                  f"{d[:, 0].min():+.0f} to {d[:, 0].max():+.0f}, north {d[:, 1].min():+.0f} to "
                  f"{d[:, 1].max():+.0f} mas/yr")
    want = np.array(GAIA) - np.array(CHEN)
    d = np.array([pm_offset(windows[0][1], 0.206, t0) for t0 in t0s])
    k = int(np.argmin(np.hypot(*(d - want).T)))
    print(f"   Gaia minus Chen is ({want[0]:+.1f}, {want[1]:+.1f}); the orbit gives "
          f"({d[k][0]:+.1f}, {d[k][1]:+.1f}) for a periastron at {t0s[k]:.1f} (+ k x {P:.2f})")


def main(path: str) -> int:
    m = json.loads(Path(path).read_text())
    plx = m["measured_motion"]["parallax_mas"]
    mjd, ra, dec, err = w2_epochs(m)
    compare(mjd, ra, dec, err, plx)
    residual_term(mjd, ra, dec, err, plx)
    orbit_ranges(2000.0 + (mjd - 51544.5) / 365.25)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
