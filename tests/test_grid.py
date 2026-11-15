import numpy as np
import pytest
from astropy.wcs import WCS

from pxs.astrometry import sky_to_px
from pxs.grid import Grid, reproject_to_grid

GRID = Grid(center_ra=331.08, center_dec=-56.79, fov_arcsec=240.0, size_px=240)


@pytest.mark.parametrize("d_ra, d_dec", [(0.0, 0.0), (0.02, 0.01), (-0.03, -0.02), (0.0, 0.03)])
def test_grid_agrees_with_astrometry(d_ra: float, d_dec: float) -> None:
    ra, dec = GRID.center_ra + d_ra, GRID.center_dec + d_dec
    x, y = GRID.sky_to_px(ra, dec)
    ex, ey = sky_to_px(ra, dec, GRID.center_ra, GRID.center_dec, GRID.fov_arcsec, GRID.size_px)
    assert x == pytest.approx(ex, abs=1e-6)
    assert y == pytest.approx(ey, abs=1e-6)


def test_centre_is_at_half_size() -> None:
    x, y = GRID.sky_to_px(GRID.center_ra, GRID.center_dec)
    assert (float(x), float(y)) == pytest.approx((120.0, 120.0), abs=1e-9)


def test_north_is_up_and_east_is_left() -> None:
    _, y_north = GRID.sky_to_px(GRID.center_ra, GRID.center_dec + 0.01)
    x_east, _ = GRID.sky_to_px(GRID.center_ra + 0.01, GRID.center_dec)
    assert y_north < 120.0
    assert x_east < 120.0


def test_reproject_puts_a_source_where_the_grid_says() -> None:
    # A FITS-style input image (row 0 south) at 2.75"/px with one bright pixel.
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [GRID.center_ra, GRID.center_dec]
    w.wcs.crpix = [50.5, 50.5]
    w.wcs.cdelt = [-2.75 / 3600, 2.75 / 3600]
    data = np.zeros((100, 100), dtype=np.float32)
    data[70, 30] = 100.0  # north-east of centre
    ra, dec = w.all_pix2world(30, 70, 0)

    out = reproject_to_grid(data, w, GRID)

    assert out.shape == GRID.shape and out.dtype == np.float32
    y_peak, x_peak = np.unravel_index(np.nanargmax(out), out.shape)
    x, y = GRID.sky_to_px(ra, dec)
    assert abs(x_peak + 0.5 - x) <= 1.5 and abs(y_peak + 0.5 - y) <= 1.5
    assert x_peak < 120 and y_peak < 120  # east is left, north is up


def test_reproject_marks_uncovered_area_as_nan() -> None:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [GRID.center_ra, GRID.center_dec]
    w.wcs.crpix = [5.5, 5.5]
    w.wcs.cdelt = [-2.75 / 3600, 2.75 / 3600]
    out = reproject_to_grid(np.ones((10, 10), dtype=np.float32), w, GRID)
    assert np.isnan(out[0, 0]) and np.isfinite(out[120, 120])


def _spx_wcs() -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [GRID.center_ra, GRID.center_dec]
    w.wcs.crpix = [25.5, 25.5]
    w.wcs.cdelt = [-6.15 / 3600, 6.15 / 3600]
    return w


def test_normalised_reproject_does_not_smear_bad_pixels() -> None:
    rng = np.random.default_rng(0)
    data = np.ones((50, 50), dtype=np.float32)
    data[rng.random((50, 50)) < 0.05] = np.nan  # 5% bad native pixels
    plain = reproject_to_grid(data, _spx_wcs(), GRID)
    norm = reproject_to_grid(data, _spx_wcs(), GRID, min_good_weight=0.5)
    # Plain bilinear turns 5% bad pixels into about 4x that area; normalised keeps it small.
    assert np.isnan(plain).mean() > 0.12
    assert np.isnan(norm).mean() < 0.06
    assert np.nanmax(np.abs(norm - 1.0)) < 1e-5  # a flat image stays flat


def test_normalised_reproject_matches_plain_without_bad_pixels() -> None:
    data = np.random.default_rng(1).normal(size=(50, 50)).astype(np.float32)
    plain = reproject_to_grid(data, _spx_wcs(), GRID)
    norm = reproject_to_grid(data, _spx_wcs(), GRID, min_good_weight=0.5)
    np.testing.assert_allclose(norm, plain, atol=1e-5)
    with pytest.raises(ValueError):
        reproject_to_grid(data, _spx_wcs(), GRID, min_good_weight=0.0)
