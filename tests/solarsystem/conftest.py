"""Fixtures for the Solar System body tests. Offline by default; network tests need PXS_NETWORK=1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from pxs.solarsystem import horizons
from pxs.solarsystem.horizons import EphemPoint
from pxs.solarsystem.phot import Measured
from pxs.solarsystem.track import Visit
from pxs.spherex import config
from pxs.spherex.read import Stamp
from pxs.spherex.types import Frame, SpecPoint

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("PXS_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set PXS_NETWORK=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PXS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.fixture
def recorded_horizons(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Serve recorded Horizons responses for exactly their recorded parameters."""
    recs = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("horizons_*.json"))]

    def fake_get(params: dict) -> dict:
        for r in recs:
            if r["params"] == params:
                return {"result": r["result"]}
        raise AssertionError(f"unexpected Horizons request {params}")

    monkeypatch.setattr(horizons, "_get", fake_get)
    return recs


def tan_header(ra: float, dec: float, crpix: tuple[float, float], mjd: float,
               rot_deg: float = 20.0, detector: int = 1) -> str:
    """A rotated TAN header standing in for a SPHEREx frame header (no SIP)."""
    c, s = np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))
    d = config.PIXSCALE_ARCSEC / 3600.0
    h = fits.Header()
    h["NAXIS"], h["NAXIS1"], h["NAXIS2"] = 2, 2040, 2040
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["CRPIX1"], h["CRPIX2"] = crpix
    h["CD1_1"], h["CD1_2"], h["CD2_1"], h["CD2_2"] = -d * c, d * s, d * s, d * c
    h["MJD-AVG"], h["DETECTOR"] = mjd, detector
    return h.tostring()


def gaussian_epsf(sigma_px: float = 0.9) -> np.ndarray:
    o, n = config.EPSF_OVERSAMPLE, config.EPSF_SIZE
    y, x = (np.mgrid[0:n, 0:n] - (n - 1) / 2) / o
    p = np.exp(-(x**2 + y**2) / (2 * sigma_px**2))
    return p / p.sum()


def make_stamp(ra: float, dec: float, mjd: float, wave_um: float, flux_mjy: float,
               body_ra: float | None = None, body_dec: float | None = None, half: int = 15,
               noise: float = 0.002, seed: int = 0, detector: int = 1) -> Stamp:
    """A stamp centred near (ra, dec) with a point source of flux_mjy at (body_ra, body_dec)."""
    rng = np.random.default_rng(seed)
    size = 2 * half + 1
    x0 = y0 = 1000 - half
    hdr = tan_header(ra, dec, (1001.0, 1001.0), mjd, detector=detector)
    psf = gaussian_epsf()
    probe = Stamp("k", np.zeros((1, 1)), np.zeros((1, 1), np.int32), np.ones((1, 1)),
                  np.zeros((1, 1)), x0, y0, 0.0, 0.0, wave_um, 0.03, mjd, detector, hdr)
    bx, by = probe.pixel_of(body_ra if body_ra is not None else ra,
                            body_dec if body_dec is not None else dec)
    img = np.zeros((size, size))
    if flux_mjy:
        yy, xx = np.mgrid[0:size, 0:size]
        sig = 0.9
        g = np.exp(-((xx + x0 - bx) ** 2 + (yy + y0 - by) ** 2) / (2 * sig**2))
        img += g / g.sum() * flux_mjy / config.MJYSR_TO_MJY
    sigma = noise / config.MJYSR_TO_MJY
    img += rng.normal(0, sigma, img.shape)
    xp, yp = probe.pixel_of(ra, dec)
    arrays = [img, np.zeros((size, size), np.int32), np.full((size, size), sigma**2),
              np.zeros((size, size))]
    for a in arrays + [psf]:
        a.setflags(write=False)
    return Stamp("k", *arrays, x0=x0, y0=y0, xpix=xp, ypix=yp, wave_um=wave_um, band_um=0.03,
                 mjd=mjd, detector=detector, header=hdr, psf=psf)


def eph(mjd: float, ra: float, dec: float, rate: float = 1.0) -> EphemPoint:
    return EphemPoint(mjd, ra, dec, rate, 0.0, 17.3, 50.0, 50.0, 90.0, 1.1)


def frame(mjd: float, det: int = 1, key: str | None = None) -> Frame:
    return Frame("spherex_qr3", f"obs{mjd}", det, mjd, key or f"k/{mjd}/{det}", 0.7, 1.1)


def spec_point(wl: float, flux: float, err: float = 0.01, mjd: float = 61000.0,
               flagged: bool = False, det: int = 1) -> SpecPoint:
    return SpecPoint(wl, 0.03, flux, err, det, flagged, mjd)


def measured(mjd: float, ra: float, dec: float, wave: float, flux: float, **kw) -> Measured:
    s = make_stamp(ra, dec, mjd, wave, flux, **kw)
    v = Visit(frame(mjd), eph(mjd, ra, dec))
    return Measured(v, s, spec_point(wave, flux, mjd=mjd))
