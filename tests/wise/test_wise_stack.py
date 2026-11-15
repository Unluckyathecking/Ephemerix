import math

import numpy as np
import pytest
from conftest import GRID, make_exposure, make_frame, make_wcs

from pxs.wise.frames import Frame
from pxs.wise.stack import _layer, stack_visit
from pxs.wise.visits import Visit

RA, DEC = GRID.center_ra, GRID.center_dec
SRC = (RA + 21 / 3600 / math.cos(math.radians(DEC)), DEC + 15 / 3600)  # 21" E, 15" N
CR = (RA - 31 / 3600 / math.cos(math.radians(DEC)), DEC - 25 / 3600)  # 31" W, 25" S
SIZE = 120  # native pixels per synthetic frame (330")


def _image(wcs, rng, source_dn=400.0, cosmic=False, saturate=False) -> np.ndarray:
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    data = 100.0 + rng.normal(0.0, 1.0, (SIZE, SIZE))  # background 100 DN, noise 1 DN
    sx, sy = wcs.all_world2pix(*SRC, 0)
    psf = np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 1.5**2))
    data = data + source_dn * psf
    if saturate:
        data[psf > 0.3] = np.nan
    if cosmic:
        cx, cy = (round(float(v)) for v in wcs.all_world2pix(*CR, 0))
        data[cy, cx] = 5000.0
    return data


def _visit(n: int, *, cosmic_in: int | None = None, saturate=False,
           shift_deg: float = 0.0) -> tuple[Visit, dict]:
    rng = np.random.default_rng(1)
    exposures = {}
    for i in range(n):
        wcs = make_wcs(RA + shift_deg + 1e-4 * i, DEC - 1e-4 * i, 15.0 * i, SIZE)
        f = make_frame(i, wcs)
        exposures[f.key] = make_exposure(
            f, wcs, _image(wcs, rng, cosmic=(i == cosmic_in), saturate=saturate))
    frames = tuple(e.frame for e in exposures.values())
    return Visit(frames=frames, target_ra=SRC[0], target_dec=SRC[1]), exposures


def _reader(exposures: dict):
    return lambda frame, grid: exposures[frame.key]


def test_source_lands_on_its_grid_pixel_and_cosmic_ray_is_rejected() -> None:
    visit, exps = _visit(7, cosmic_in=3)
    s = stack_visit(visit, "W2", GRID, read=_reader(exps))
    assert s is not None and s.image.shape == GRID.shape and s.n_exposures == 7
    peak_y, peak_x = np.unravel_index(np.nanargmax(s.image), s.image.shape)
    x, y = GRID.sky_to_px(*SRC)
    assert (peak_x, peak_y) == (math.floor(float(x)), math.floor(float(y)))
    cx, cy = (math.floor(float(v)) for v in GRID.sky_to_px(*CR))
    assert abs(s.image[cy, cx]) < 3.0  # 5000 DN in one frame, gone after clipping
    assert abs(np.nanmedian(s.image)) < 0.5  # background subtracted
    assert (s.mission, s.band, s.unit, s.native_pixscale_arcsec) == ("WISE", "W2", "DN", 2.75)
    assert s.wavelength_um == (4.0, 5.2) and s.warnings == ()
    assert s.mjd == pytest.approx(np.mean([f.mjd for f in visit.frames]))


def test_saturated_core_is_flagged_and_filled() -> None:
    visit, exps = _visit(5, saturate=True)
    s = stack_visit(visit, "W2", GRID, read=_reader(exps))
    assert "saturated" in s.warnings
    x, y = (math.floor(float(v)) for v in GRID.sky_to_px(*SRC))
    assert np.isfinite(s.image[y, x]) and s.image[y, x] == np.nanmax(s.image)
    assert 0.0 < s.flag_fraction < 0.05


def test_partial_coverage_is_reported() -> None:
    visit, exps = _visit(4, shift_deg=0.035)  # frames pushed east, grid's west edge uncovered
    s = stack_visit(visit, "W2", GRID, read=_reader(exps))
    assert s is not None and "partial coverage" in s.warnings
    assert np.isnan(s.image).any()


def test_no_coverage_returns_none() -> None:
    visit, exps = _visit(3)
    assert stack_visit(visit, "W1", GRID, read=_reader(exps)) is None  # no W1 frames
    assert stack_visit(visit, "W2", GRID, read=lambda f, g: None) is None


def test_failed_reads_are_skipped_and_counted() -> None:
    visit, exps = _visit(5)
    bad = visit.frames[0].key

    def flaky(frame: Frame, grid):
        if frame.key == bad:
            raise ConnectionError("gave up after retries")
        return exps[frame.key]

    s = stack_visit(visit, "W2", GRID, read=flaky)
    assert s.n_exposures == 4 and "1 frames failed to download" in s.warnings


def test_cap_limits_frames_read() -> None:
    visit, exps = _visit(6)
    read = []
    s = stack_visit(visit, "W2", GRID, max_frames=3,
                    read=lambda f, g: read.append(f.key) or exps[f.key])
    assert len(read) == 3 and s.n_exposures == 3


def test_scattered_flagged_pixels_do_not_blank_their_neighbours() -> None:
    wcs = make_wcs(RA, DEC, 20.0, SIZE)
    data = np.random.default_rng(2).normal(0.0, 1.0, (SIZE, SIZE))
    data[np.random.default_rng(3).random((SIZE, SIZE)) < 0.06] = np.nan  # like late NEOWISE
    image, covered = _layer(make_exposure(make_frame(0, wcs), wcs, data), GRID)
    assert covered.all()
    assert np.isnan(image).mean() < 0.08  # plain bilinear resampling gave about 0.3


def test_thin_visit_leaves_flagged_pixels_empty() -> None:
    visit, exps = _visit(1)
    exp = next(iter(exps.values()))
    holes = np.random.default_rng(4).random(exp.data.shape) < 0.05
    holes[::2, ::2] = holes[::2, ::2] | (np.random.default_rng(5).random((60, 60)) < 0.2)
    flagged = {exp.frame.key: type(exp)(exp.frame, np.where(holes, np.nan, exp.data), exp.wcs,
                                        exp.y0, exp.full_shape, exp.header)}
    s = stack_visit(visit, "W2", GRID, read=_reader(flagged))
    peak = np.nanmax(s.image)
    assert np.isnan(s.image).any()  # flagged clusters stay NaN ...
    assert (s.image == peak).sum() == 1  # ... and are not painted with the maximum


def test_bad_band_raises() -> None:
    visit, _ = _visit(1)
    with pytest.raises(ValueError):
        stack_visit(visit, "W3", GRID)


def test_bad_pixel_cluster_on_empty_sky_takes_the_local_level() -> None:
    # Code review R7: a fixed bad-pixel cluster used to become the image maximum (a fake star).
    from pxs.wise.combine import fill_holes

    rng = np.random.default_rng(0)
    image = rng.normal(0.0, 1.0, (60, 60)).astype(np.float32)
    image[10, 10] = 5000.0  # an unrelated bright star elsewhere
    hole = np.zeros_like(image, dtype=bool)
    hole[40:43, 40:43] = True
    image[hole] = np.nan
    out = fill_holes(image, hole)
    assert np.all(out[hole] < 5.0) and np.all(np.isfinite(out[hole]))
    assert np.isnan(image[hole]).all()  # input untouched


def test_saturated_core_is_handed_on_as_a_mask() -> None:
    # The centroid ignores these pixels and the renderer draws them white.
    visit, exps = _visit(5, saturate=True)
    s = stack_visit(visit, "W2", GRID, read=_reader(exps))
    x, y = (math.floor(float(v)) for v in GRID.sky_to_px(*SRC))
    assert s.saturated_mask is not None and s.saturated_mask.shape == GRID.shape
    assert s.saturated_mask[y, x] and s.saturated_mask.sum() < 50


def test_flagged_cluster_takes_the_ring_median_not_its_brightest_pixel() -> None:
    from pxs.wise.combine import fill_holes

    image = np.random.default_rng(1).normal(0.0, 1.0, (40, 40)).astype(np.float32)
    image[19:23, 17] = 4.0  # one bright-ish column next to the cluster
    hole = np.zeros_like(image, dtype=bool)
    hole[19:22, 18:21] = True
    out = fill_holes(np.where(hole, np.nan, image).astype(np.float32), hole)
    assert np.all(np.abs(out[hole]) < 1.5)


def test_layer_is_bit_identical_to_two_separate_reprojections() -> None:
    # _layer resamples data and good-pixel weight in one call; it must match doing it twice.
    from pxs.grid import reproject_to_grid
    from pxs.wise.stack import MIN_GOOD_WEIGHT

    wcs = make_wcs(RA, DEC, 20.0, SIZE)
    data = np.random.default_rng(2).normal(100.0, 1.0, (SIZE, SIZE))
    data[np.random.default_rng(3).random((SIZE, SIZE)) < 0.06] = np.nan
    exp = make_exposure(make_frame(0, wcs), wcs, data)
    good = np.isfinite(exp.data)
    values = reproject_to_grid(np.where(good, exp.data - np.median(exp.data[good]), 0.0), wcs,
                               GRID)
    weight = reproject_to_grid(good.astype(np.float32), wcs, GRID)
    usable = np.isfinite(weight) & (np.nan_to_num(weight) >= MIN_GOOD_WEIGHT)
    with np.errstate(invalid="ignore", divide="ignore"):
        expected = np.where(usable, values / weight, np.nan).astype(np.float32)
    image, covered = _layer(exp, GRID)
    assert np.array_equal(image, expected, equal_nan=True)
    assert np.array_equal(covered, np.isfinite(weight))
