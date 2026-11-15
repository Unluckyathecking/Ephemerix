from dataclasses import replace

import numpy as np
import pytest
from astropy.io import fits

from pxs.grid import Grid
from pxs.spherex import Frame, Pass, Target, stack, stack_pass
from pxs.spherex.stack import combine, stamp_half
from pxs.spherex.stamps import Batch

from .conftest import synthetic_stamp, tan_header

RA, DEC = 150.0, 2.0
SRC = (150.0 + 13 / 3600 / np.cos(np.radians(2.0)), 2.0 - 7 / 3600)  # on pixel centre (23.5, 33.5)
GRID = Grid(RA, DEC, fov_arcsec=120.0, size_px=60)


def _frame(i: int, mjd: float, det: int = 6) -> Frame:
    return Frame("spherex_dr1", f"o{i}", det, mjd, f"key{i}", 4.4, 5.0)


def _stamp_with_source(mjd: float, rot: float, wave: float = 4.5, seed: int = 0):
    """Grid-sized stamp, frame rotated by `rot`, unit-peak Gaussian source at SRC."""
    half = stamp_half(GRID)
    n = 2 * half + 1
    s = synthetic_stamp(np.zeros((n, n)), wave=wave, ra=RA, dec=DEC, mjd=mjd)
    h = fits.Header.fromstring(tan_header(RA, DEC, (1001.0, 1001.0), rot_deg=rot, mjd=mjd))
    s = replace(s, header=h.tostring())
    sx, sy = s.wcs().world_to_pixel_values(*SRC)
    yy, xx = np.mgrid[0:n, 0:n]
    img = np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 0.8**2))
    img = img + np.random.default_rng(seed).normal(0, 0.01, (n, n))
    return replace(s, image=img + s.zodi)


@pytest.fixture
def fake_reader(monkeypatch):
    def install(stamps):
        def fake(jobs, half, with_psf=True, store=None, workers=8):
            by_key = {f.s3_key: s for f, s in zip([j[0] for j in jobs], stamps)}
            return Batch(tuple((j[0], by_key[j[0].s3_key]) for j in jobs), 0, 0)
        monkeypatch.setattr(stack, "read_many", fake)
    return install


def test_stack_puts_the_source_on_the_right_grid_pixel(fake_reader) -> None:
    rots = [10.0, 40.0, 75.0, 120.0]
    stamps = [_stamp_with_source(61000 + i, r, seed=i) for i, r in enumerate(rots)]
    fake_reader(stamps)
    pas = Pass(tuple(_frame(i, 61000 + i) for i in range(4)))
    st = stack_pass(pas, GRID, (4.4, 4.8))
    assert st is not None
    assert st.image.shape == GRID.shape and st.image.dtype == np.float32
    px, py = (float(v) for v in GRID.sky_to_px(*SRC))
    iy, ix = np.unravel_index(np.nanargmax(st.image), st.image.shape)
    # Bilinear resampling peaks at the nearest native sample (6.15" = 3 grid px), so the
    # brightest pixel is only good to about a grid pixel; the centroid is much better.
    assert abs(ix - int(np.floor(px))) <= 1 and abs(iy - int(np.floor(py))) <= 1
    yy, xx = np.mgrid[0:60, 0:60] + 0.5
    w = np.nan_to_num(st.image).clip(0) * (np.hypot(xx - px, yy - py) < 6)
    assert (w * xx).sum() / w.sum() == pytest.approx(px, abs=0.25)
    assert (w * yy).sum() / w.sum() == pytest.approx(py, abs=0.25)
    assert ix < 30 and iy > 30  # east is left, south is down
    assert st.n_exposures == 4 and st.date_span_days == pytest.approx(3.0)
    assert st.band == "4.4-4.8 um" and st.wavelength_um == (4.4, 4.8)
    assert st.flag_fraction == 0.0 and st.warnings == ()


def test_stack_returns_none_when_no_frame_covers_the_window(fake_reader) -> None:
    fake_reader([_stamp_with_source(61000, 0.0, wave=4.5)])
    pas = Pass((_frame(0, 61000),))
    assert stack_pass(pas, GRID, (1.0, 2.0)) is None  # outside the detector's range
    assert stack_pass(pas, GRID, (4.6, 4.9)) is None  # wavelength at the target is 4.5


def test_stack_warns_when_the_target_is_saturated(fake_reader) -> None:
    s = _stamp_with_source(61000, 0.0)
    tx, ty = s.pixel_of(*SRC)
    flags = np.zeros_like(s.flags)
    flags[round(ty) - s.y0, round(tx) - s.x0] = 2  # OVERFLOW
    fake_reader([replace(s, flags=flags)])
    target = Target("star", SRC[0], SRC[1], 2025.0, 0.0, 0.0)
    st = stack_pass(Pass((_frame(0, 61000),)), GRID, (4.4, 4.8), target=target)
    assert st.warnings == ("saturated",)
    assert 0 < st.flag_fraction < 0.01


def test_one_saturated_frame_of_five_does_not_mark_the_stack(fake_reader) -> None:
    stamps = [_stamp_with_source(61000 + i, 20.0 * i, seed=i) for i in range(5)]
    tx, ty = stamps[0].pixel_of(*SRC)
    flags = np.zeros_like(stamps[0].flags)
    flags[round(ty) - stamps[0].y0, round(tx) - stamps[0].x0] = 2  # OVERFLOW in one frame
    stamps[0] = replace(stamps[0], flags=flags)
    fake_reader(stamps)
    target = Target("star", SRC[0], SRC[1], 2025.0, 0.0, 0.0)
    pas = Pass(tuple(_frame(i, 61000 + i) for i in range(5)))
    st = stack_pass(pas, GRID, (4.4, 4.8), target=target)
    assert "saturated" not in st.warnings


def test_combine_rejects_a_single_frame_outlier() -> None:
    images = np.ones((5, 2, 2))
    images[2, 0, 0] = 100.0  # cosmic ray in one frame
    variances = np.full((5, 2, 2), 0.01)
    out = combine(images, variances)
    assert out[0, 0] == pytest.approx(1.0)


def test_combine_keeps_a_source_that_varies_across_frames() -> None:
    images = np.array([1.0, 1.5, 2.0, 2.5, 3.0])[:, None, None] * np.ones((5, 1, 1))
    out = combine(images, np.full((5, 1, 1), 0.001))
    assert out[0, 0] == pytest.approx(2.0)


def test_combine_is_inverse_variance_weighted_and_nan_where_empty() -> None:
    images = np.array([[[1.0, np.nan]], [[3.0, np.nan]]])
    variances = np.array([[[1.0, 1.0]], [[3.0, 1.0]]])
    out = combine(images, variances)
    assert out[0, 0] == pytest.approx((1.0 + 3.0 / 3) / (1 + 1 / 3))
    assert np.isnan(out[0, 1])


@pytest.mark.parametrize("window", [(2.0, 1.0), (0.1, 1.0), (4.0, float("nan"))])
def test_window_is_validated(window) -> None:
    with pytest.raises(ValueError):
        stack_pass(Pass((_frame(0, 61000),)), GRID, window)


def test_one_call_reprojection_matches_the_grid_function_bit_for_bit() -> None:
    from pxs.grid import reproject_to_grid
    from pxs.spherex.stack import MIN_GOOD_WEIGHT, reproject_planes

    s = _stamp_with_source(61000.0, 33.0, seed=3)
    rng = np.random.default_rng(7)
    img = np.array(s.image, dtype=np.float32)
    img[rng.random(img.shape) < 0.05] = np.nan  # flagged pixels
    var = np.where(np.isfinite(img), np.float32(1e-3), np.nan).astype(np.float32)
    w = s.wcs()
    got = reproject_planes([img, var], w, GRID, MIN_GOOD_WEIGHT)
    for plane, out in zip([img, var], got):
        ref = reproject_to_grid(plane, w, GRID, MIN_GOOD_WEIGHT)
        assert out.dtype == ref.dtype and np.array_equal(out, ref, equal_nan=True)
