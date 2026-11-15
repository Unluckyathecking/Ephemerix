"""Shared fixtures for the WISE tests. Live-network tests are marked ``network`` and run only
with PXS_NETWORK=1."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from astropy.wcs import WCS

from pxs.grid import Grid
from pxs.wise.frames import Frame
from pxs.wise.reader import Exposure

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "network: needs live IRSA/S3 access (PXS_NETWORK=1)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("PXS_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="live network test; set PXS_NETWORK=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("PXS_NETWORK") != "1":
        monkeypatch.setenv("PXS_WISE_CACHE", str(tmp_path / "cache"))
        # No committed frame lists and no source-table reads unless a test opts in.
        monkeypatch.setenv("PXS_WISE_FRAMES", str(tmp_path / "no-frame-lists"))
        monkeypatch.setattr("pxs.wise.neoqual.quality", lambda *a, **k: {})
        # No frame listing from the bucket either: a phase IRSA did not list stays unlisted.
        monkeypatch.setattr("pxs.wise.bucketsearch.phase_frames", lambda *a, **k: None)


GRID = Grid(center_ra=150.0, center_dec=20.0, fov_arcsec=120.0, size_px=60)


def make_wcs(ra: float, dec: float, rot_deg: float, size: int) -> WCS:
    """A TAN WCS at 2.75"/px, FITS-style (row 0 south), rotated by rot_deg."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [size / 2 + 0.5, size / 2 + 0.5]
    s = 2.75 / 3600
    c, n = np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))
    w.wcs.cd = np.array([[-s * c, s * n], [s * n, s * c]])
    w.pixel_shape = (size, size)
    return w


def make_frame(i: int, wcs: WCS, qual: int | None = 10, band: str = "W2",
               mjd: float = 58000.0) -> Frame:
    corners = tuple((float(a), float(b)) for a, b in wcs.calc_footprint())
    return Frame(phase="neowiser", scan_id=f"{10000 + i:05d}a", frame_num=i, band=band,
                 mjd=mjd + i * 0.05, corners=corners, qual_frame=qual)


def make_exposure(frame: Frame, wcs: WCS, data: np.ndarray) -> Exposure:
    return Exposure(frame=frame, data=data.astype(np.float32), wcs=wcs, y0=0,
                    full_shape=data.shape, header=wcs.to_header())


@pytest.fixture(autouse=True)
def _closed_breakers():
    """Every test starts and ends with every service's circuit breaker closed (they are
    process-wide, so a test that simulates a dead archive must not affect the next one)."""
    from pxs import concurrency

    concurrency.reset_breakers()
    yield
    concurrency.reset_breakers()
