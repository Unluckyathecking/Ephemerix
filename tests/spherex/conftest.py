"""Shared fixtures for the SPHEREx tests. Offline by default; network tests need PXS_NETWORK=1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from pxs.spherex import config
from pxs.spherex.net import BlockStore
from pxs.spherex.read import Stamp

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
    """Every test gets its own empty cache directory."""
    monkeypatch.setenv("PXS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


def _no_network(key: str, start: int, end: int) -> tuple[bytes, int]:
    raise AssertionError(f"unexpected network read of {key}[{start}:{end}]")


@pytest.fixture
def recorded() -> dict:
    """Recorded frames: name -> {key, ra, dec, half, block}."""
    return json.loads((FIXTURES / "stamps.json").read_text())


@pytest.fixture
def offline_store(recorded: dict) -> BlockStore:
    """A BlockStore that serves only the recorded blocks and fails on anything else."""
    block = next(iter(recorded.values()))["block"]
    return BlockStore(fetch=_no_network, root=FIXTURES, block=block)


def tan_header(ra: float, dec: float, crpix: tuple[float, float], scale_arcsec: float = 6.15,
               rot_deg: float = 30.0, mjd: float = 61000.0, detector: int = 6) -> str:
    """A plain rotated TAN header standing in for a SPHEREx frame header (no SIP)."""
    c, s = np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))
    d = scale_arcsec / 3600.0
    h = fits.Header()
    h["NAXIS"], h["NAXIS1"], h["NAXIS2"] = 2, 2040, 2040
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["CRPIX1"], h["CRPIX2"] = crpix
    h["CD1_1"], h["CD1_2"], h["CD2_1"], h["CD2_2"] = -d * c, d * s, d * s, d * c
    h["MJD-AVG"], h["DETECTOR"] = mjd, detector
    return h.tostring()


def flat_wave(wave: float, band: float = 0.04) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs = np.array([1.0, 2040.0])
    v = np.zeros((2, 2, 2))
    v[..., 0], v[..., 1] = wave, band
    return xs, xs.copy(), v


def synthetic_stamp(image: np.ndarray, *, flags: np.ndarray | None = None, var: float = 1e-4,
                    zodi: float = 0.2, psf: np.ndarray | None = None, wave: float = 4.5,
                    ra: float = 150.0, dec: float = 2.0, mjd: float = 61000.0,
                    detector: int = 6) -> Stamp:
    """A Stamp around full-frame pixel (1000, 1000), with the target at the stamp centre."""
    n = image.shape[0]
    half = n // 2
    x0 = y0 = 1000 - half
    header = tan_header(ra, dec, (1001.0, 1001.0), mjd=mjd, detector=detector)
    return Stamp(
        key="synthetic", image=image + zodi,
        flags=np.zeros_like(image, dtype=np.int32) if flags is None else flags,
        variance=np.full_like(image, var), zodi=np.full_like(image, zodi), x0=x0, y0=y0,
        xpix=1000.0, ypix=1000.0, wave_um=wave, band_um=0.04, mjd=mjd, detector=detector,
        header=header, psf=psf, wave_table=flat_wave(wave))


@pytest.fixture
def gaussian_psf() -> np.ndarray:
    """A normalised 33x33 ePSF oversampled x5 (Gaussian, FWHM ~1.7 native px)."""
    o, c = config.EPSF_OVERSAMPLE, (config.EPSF_SIZE - 1) / 2
    yy, xx = np.mgrid[0:config.EPSF_SIZE, 0:config.EPSF_SIZE]
    sigma = 0.72 * o
    p = np.exp(-((xx - c) ** 2 + (yy - c) ** 2) / (2 * sigma**2))
    return p / p.sum()


@pytest.fixture(autouse=True)
def _closed_breakers():
    """Every test starts and ends with every service's circuit breaker closed (they are
    process-wide, so a test that simulates a dead archive must not affect the next one)."""
    from pxs import concurrency

    concurrency.reset_breakers()
    yield
    concurrency.reset_breakers()
