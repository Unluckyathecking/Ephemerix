"""Helpers for the frame-index tests: recorded header bytes and synthetic frames."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from pxs.spherex.indexfmt import header_end, parse_frame, rebuild_key

HEADERS = Path(__file__).parent / "fixtures" / "headers"
REAL_D1 = HEADERS / "level2_2025W17_4B_0001_1D1_spx_l2b-v27-2026-196.bin"
REAL_DEEP = HEADERS / "level2_2025W17_4B_0021_1D3_spx_l2b-v27-2026-196.bin"
REAL_QR3 = HEADERS / "level2_2026W40_2A_0001_3D1_spx_l2b-v27-2026-285.bin"
KEY_D1 = "dr1/level2/2025W17_4B/l2b-v27-2026-196/1/level2_2025W17_4B_0001_1D1_spx_l2b-v27-2026-196.fits"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


def image_hdr(path: Path = REAL_D1) -> fits.Header:
    data = path.read_bytes()
    p = header_end(data)
    return fits.Header.fromstring(data[p:header_end(data, p)].decode("ascii"))


def fake_file(crval1: float, crval2: float, *, obs: str = "2025W17_4B_0100_1", det: int = 1,
              mjd: float = 60790.0, sps: str = "all_sky") -> bytes:
    """Leading bytes of a file like the recorded D1 frame but pointing at (crval1, crval2)."""
    data = REAL_D1.read_bytes()
    p = header_end(data)
    hdr = image_hdr()
    hdr["CRVAL1"], hdr["CRVAL2"] = crval1, crval2
    hdr["LATPOLE"] = crval2
    hdr["OBSID"], hdr["DETECTOR"], hdr["SPS_FLAGS"] = obs, det, sps
    hdr["MJD-BEG"], hdr["MJD-END"] = mjd - 0.0007, mjd + 0.0007
    return data[:p] + hdr.tostring(endcard=True, padding=True).encode("ascii") + b"\0" * 2880


def fake_row(crval1: float, crval2: float, *, week: str = "2025W17_4B", release: str = "dr1",
             obs: str = "2025W17_4B_0100_1", det: int = 1, mjd: float = 60790.0,
             sps: str = "all_sky") -> dict:
    key = rebuild_key(release, week, "l2b-v27-2026-196", obs, det)
    return parse_frame(key, 65_000_000, fake_file(crval1, crval2, obs=obs, det=det, mjd=mjd,
                                                  sps=sps))


def astropy_wcs(hdr: fits.Header) -> WCS:
    keep = fits.Header([c for c in hdr.cards if c.keyword.startswith(
        ("CRPIX", "CRVAL", "PC", "CDELT", "CTYPE", "CUNIT", "LONPOLE", "LATPOLE", "A_", "B_",
         "AP_", "BP_", "RADESYS"))
        and not c.keyword.endswith(("A", "W"))])
    keep["WCSAXES"] = 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return WCS(keep)


def sky_at(row_like_hdr: fits.Header, x: float, y: float) -> tuple[float, float]:
    """(ra, dec) of FITS pixel (x, y) from astropy, the ground truth for coverage tests."""
    ra, dec = astropy_wcs(row_like_hdr).all_pix2world(np.array([x]), np.array([y]), 1)
    return float(ra[0]) % 360.0, float(dec[0])
