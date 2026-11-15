import numpy as np
import pytest
from astropy.io import fits

from pxs.spherex.fitsfile import RangeFile
from pxs.spherex.net import BlockStore, http_fetch
from pxs.spherex.read import read_stamp, wave_at

from .conftest import FIXTURES

PLANES = ("image", "flags", "variance", "zodi")


def _read(store: BlockStore, rec: dict, **kw):
    return read_stamp(store, rec["key"], rec["ra"], rec["dec"], half=rec["half"], **kw)


def test_reader_matches_probe_stamp_bit_for_bit(offline_store, recorded) -> None:
    """The probe (fsspec + astropy section) read the same frame independently."""
    s = _read(offline_store, recorded["eps_d3"])
    probe = np.load(FIXTURES / "probe_crop.npz")
    for name in PLANES:
        assert np.array_equal(getattr(s, name), probe[name], equal_nan=True), name
    assert np.array_equal(s.psf, probe["psf"])
    assert s.wave_um == pytest.approx(float(probe["wave"]), abs=1e-12)


@pytest.mark.parametrize("name", ["eps_d3", "eps_d6", "barnard"])
def test_prefetch_and_simple_reads_are_identical(offline_store, recorded, name) -> None:
    fast = _read(offline_store, recorded[name], prefetch=True)
    simple = _read(offline_store, recorded[name], prefetch=False)
    for attr in PLANES + ("psf",):
        assert np.array_equal(getattr(fast, attr), getattr(simple, attr), equal_nan=True)
    assert (fast.x0, fast.y0, fast.wave_um, fast.mjd) == (
        simple.x0, simple.y0, simple.wave_um, simple.mjd)


def test_stamp_metadata(offline_store, recorded) -> None:
    s = _read(offline_store, recorded["eps_d6"])
    assert s.detector == 6
    assert s.image.shape == (11, 11) and s.flags.dtype == np.int32
    assert abs(s.xpix - (s.x0 + 5)) <= 0.5 and abs(s.ypix - (s.y0 + 5)) <= 0.5
    assert 4.4 < s.wave_um < 5.0 and 0.02 < s.band_um < 0.06
    assert not s.image.flags.writeable


def test_stamp_wcs_is_the_frame_wcs_shifted(offline_store, recorded) -> None:
    s = _read(offline_store, recorded["eps_d3"])
    full = fits.Header.fromstring(s.header)
    from pxs.spherex.read import _wcs
    for px, py in [(0.0, 0.0), (10.0, 3.0), (5.5, 9.25)]:
        a = s.wcs().pixel_to_world_values(px, py)
        b = _wcs(full).pixel_to_world_values(px + s.x0, py + s.y0)
        assert np.allclose(a, b, rtol=0, atol=1e-10)
    assert s.pixel_of(recorded["eps_d3"]["ra"], recorded["eps_d3"]["dec"]) == pytest.approx(
        (s.xpix, s.ypix), abs=1e-6)


def test_position_off_the_detector_gives_none(offline_store, recorded) -> None:
    rec = recorded["eps_d3"]
    assert read_stamp(offline_store, rec["key"], (rec["ra"] + 20) % 360, rec["dec"]) is None


def _epsf_rows(store: BlockStore, key: str, x: float, y: float) -> tuple[list[np.void], np.void]:
    """EPSF row 0 and the row of the bin containing (x, y), read from the recorded bytes."""
    with fits.open(RangeFile(store, key), lazy_load_hdus=True, memmap=False) as h:
        h.readall()
        e = h["EPSF"]
        rowlen, loc = e.header["NAXIS1"], e.fileinfo()["datLoc"]
        dtype = e.columns.dtype.newbyteorder(">")
        n = h["IMAGE"].header["NAXIS1"]
        wrow = h["WCS-WAVE"].data[0]

        def row(i: int) -> np.void:
            return np.frombuffer(store.read(key, loc + i * rowlen, loc + (i + 1) * rowlen), dtype)[0]

        first = row(0)
        nx = round(n / float(first["XWIDTH"]))
        i = int(y / first["YWIDTH"]) * nx + min(int(x / first["XWIDTH"]), nx - 1)
        return [first, row(i)], wrow


@pytest.mark.parametrize("name, offset_nm", [("eps_d3", 0.0), ("eps_d6", 6.6)])
def test_wavelength_lookup_matches_epsf_cwave(offline_store, recorded, name, offset_nm) -> None:
    """Report check 3: WCS-WAVE agrees with CWAVE to <1 nm on D1-D4; D5/D6 sit +6.6 nm redder."""
    s = _read(offline_store, recorded[name])
    rows, wrow = _epsf_rows(offline_store, recorded[name]["key"], s.xpix, s.ypix)
    for r in rows:
        xc = (int(r["BINX"]) + 0.5) * float(r["XWIDTH"]) - 0.5
        yc = (int(r["BINY"]) + 0.5) * float(r["YWIDTH"]) - 0.5
        wave, _ = wave_at(wrow, xc, yc)
        assert (wave - float(r["CWAVE"])) * 1000 == pytest.approx(offset_nm, abs=1.5)


def test_wave_at_bilinear_on_a_known_table() -> None:
    xs = np.array([1.0, 11.0])
    v = np.zeros((2, 2, 2))
    v[:, :, 0] = [[1.0, 2.0], [3.0, 4.0]]  # [iy, ix]
    v[:, :, 1] = 0.05
    row = {"X": xs, "Y": xs, "VALUES": v}
    assert wave_at(row, 0.0, 0.0) == pytest.approx((1.0, 0.05))
    assert wave_at(row, 10.0, 0.0)[0] == pytest.approx(2.0)
    assert wave_at(row, 5.0, 5.0)[0] == pytest.approx(2.5)  # 1-based (6, 6) is the midpoint


@pytest.mark.network
def test_live_read_matches_recording(offline_store, recorded, tmp_path) -> None:
    rec = recorded["eps_d6"]
    live = _read(BlockStore(fetch=http_fetch, root=tmp_path), rec)
    offline = _read(offline_store, rec)
    for attr in PLANES + ("psf",):
        assert np.array_equal(getattr(live, attr), getattr(offline, attr), equal_nan=True)
