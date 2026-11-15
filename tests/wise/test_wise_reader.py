import numpy as np
import pytest
from astropy.io import fits
from conftest import FIXTURES

from pxs.grid import Grid
from pxs.wise.frames import Frame
from pxs.wise.reader import frame_wcs, read_exposure, read_header, row_range

HEADER_BYTES = (FIXTURES / "54429b187-w2-int-1b.hdr").read_bytes()
FRAME = Frame(phase="neowiser", scan_id="54429b", frame_num=187, band="W2", mjd=56700.0,
              corners=())


def _fake_file() -> tuple[bytes, list]:
    """A full int file: the recorded real header, then rows whose value is the row number."""
    header = fits.Header.fromstring(HEADER_BYTES.decode("ascii"))
    ny, nx = header["NAXIS2"], header["NAXIS1"]
    padded = HEADER_BYTES + b" " * (-len(HEADER_BYTES) % 2880)
    rows = np.repeat(np.arange(ny, dtype=">f4")[:, None], nx, axis=1)
    calls: list = []
    return padded + rows.tobytes(), calls


def _fetcher(blob: bytes, calls: list):
    def fetch(key: str, start: int, stop: int) -> bytes:
        calls.append((key, start, stop))
        return blob[start:stop]
    return fetch


def test_header_parses_with_sip() -> None:
    blob, calls = _fake_file()
    header, data_start = read_header(FRAME.key, _fetcher(blob, calls))
    assert data_start % 2880 == 0 and data_start >= len(HEADER_BYTES)
    w = frame_wcs(header)
    assert w.sip is not None and header["CTYPE1"].endswith("-SIP")


def test_sliced_wcs_matches_full_wcs_far_from_centre() -> None:
    header = fits.Header.fromstring(HEADER_BYTES.decode("ascii"))
    full = frame_wcs(header)
    y0 = 700
    sliced = full.slice((slice(y0, 900), slice(None)))
    a = full.all_pix2world([[1000.0, 850.0]], 0)
    b = sliced.all_pix2world([[1000.0, 850.0 - y0]], 0)
    assert np.allclose(a, b, atol=1e-8)


def test_read_exposure_fetches_header_then_only_the_needed_rows() -> None:
    blob, calls = _fake_file()
    header = fits.Header.fromstring(HEADER_BYTES.decode("ascii"))
    ra, dec = frame_wcs(header).all_pix2world([[300.0, 400.0]], 0)[0]
    grid = Grid(center_ra=float(ra), center_dec=float(dec), fov_arcsec=240.0, size_px=120)
    exp = read_exposure(FRAME, grid, _fetcher(blob, calls))
    assert exp is not None and len(calls) == 2
    assert np.array_equal(exp.data[:, 0], np.arange(exp.y0, exp.y0 + exp.data.shape[0]))
    assert exp.data.shape[0] < 200  # a 4' grid needs about 90-130 rows, not the frame
    x, y = exp.wcs.all_world2pix(ra, dec, 0)
    assert (float(x), float(y) + exp.y0) == pytest.approx((300.0, 400.0), abs=1e-3)


def test_grid_off_the_frame_reads_nothing_more() -> None:
    blob, calls = _fake_file()
    header = fits.Header.fromstring(HEADER_BYTES.decode("ascii"))
    ra, dec = frame_wcs(header).all_pix2world([[500.0, 5000.0]], 0)[0]
    grid = Grid(center_ra=float(ra), center_dec=float(dec), fov_arcsec=240.0, size_px=120)
    assert row_range(frame_wcs(header), 1016, grid) is None
    assert read_exposure(FRAME, grid, _fetcher(blob, calls)) is None
    assert len(calls) == 1


def test_wcs_from_the_wcs_cards_alone_is_bit_identical() -> None:
    from pxs.wise.reader import wcs_header

    text = HEADER_BYTES.decode("ascii")
    full = frame_wcs(fits.Header.fromstring(text))
    small_header = wcs_header(text)
    small = frame_wcs(small_header)
    assert len(small_header) < 120 and small_header["BITPIX"] == -32
    x, y = np.meshgrid(np.linspace(-50, 1100, 40), np.linspace(-50, 1100, 40))
    a, b = full.all_pix2world(x, y, 0), small.all_pix2world(x, y, 0)
    assert all(np.array_equal(p, q) for p, q in zip(a, b))
    c, d = full.all_world2pix(a[0], a[1], 0), small.all_world2pix(a[0], a[1], 0)
    assert all(np.array_equal(p, q) for p, q in zip(c, d))
