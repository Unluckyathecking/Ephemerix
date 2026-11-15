import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from build_fakes import GRID, gaussian_stack

from pxs import centroid, render

PIX = GRID.pixscale_arcsec
RADIUS = 30.0  # arcsec


def test_render_is_deterministic(tmp_path: Path) -> None:
    st = gaussian_stack(GRID, (100.3, 140.7), 58000.0, seed=3)
    stretch = render.shared_stretch([st])
    a = render.write_png(st, stretch, tmp_path / "a.png").read_bytes()
    b = render.write_png(st, stretch, tmp_path / "b.png").read_bytes()
    assert a == b


def test_stretch_is_shared_so_equal_sources_look_equal() -> None:
    # Same source, different sky background: the shared stretch removes each frame's own
    # background, so the source peak gets the same grey level in both.
    a = gaussian_stack(GRID, (120.5, 120.5), 58000.0, background=10.0, seed=1)
    b = gaussian_stack(GRID, (120.5, 120.5), 59000.0, background=55.0, seed=1)
    stretch = render.shared_stretch([a, b])
    pa, pb = render.to_uint8(a, stretch), render.to_uint8(b, stretch)
    assert pa[120, 120] == pb[120, 120]
    assert pa[120, 120] > 200  # bright source is white
    assert np.median(pa) < 100  # on a dark sky


def test_nan_renders_at_background_level_not_black() -> None:
    st = gaussian_stack(GRID, None, 58000.0, seed=2)
    img = st.image.copy()
    img[:20, :20] = np.nan
    st = replace(st, image=img)
    px = render.to_uint8(st, render.shared_stretch([st]))
    assert px[5, 5] > 0
    assert abs(int(px[5, 5]) - int(np.median(px[40:, 40:]))) <= 2


def test_thumbnail_is_square(tmp_path: Path) -> None:
    from PIL import Image

    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0)
    path = render.write_thumb(st, render.shared_stretch([st]), tmp_path / "t.png")
    assert Image.open(path).size == (render.THUMB_PX, render.THUMB_PX)


@pytest.mark.parametrize("seed", range(6))
def test_centroid_recovers_source_within_error(seed: int) -> None:
    truth = (117.37, 124.81)  # edge-convention pixels
    st = gaussian_stack(GRID, truth, 58000.0, amp=15.0, seed=seed)
    c = centroid.measure(st, (120.0, 120.0), PIX, RADIUS)
    assert c is not None
    off_arcsec = np.hypot(c.x - truth[0], c.y - truth[1]) * PIX
    assert off_arcsec < 3.5 * c.err_arcsec
    assert c.err_arcsec < 1.0


def test_centroid_error_is_inflated_for_resampled_pixels() -> None:
    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=15.0, seed=4)
    fine = centroid.measure(replace(st, native_pixscale_arcsec=PIX * 2.82), (120, 120), PIX, 30)
    coarse = centroid.measure(st, (120, 120), PIX, 30)
    assert coarse is not None and fine is not None
    # Same image, same PSF size; only the correlation factor differs (2.75 vs 2.82).
    assert coarse.err_arcsec == pytest.approx(fine.err_arcsec * 2.75 / 2.82, rel=0.05)


@pytest.mark.parametrize("seed", range(5))
def test_centroid_is_none_on_pure_noise(seed: int) -> None:
    st = gaussian_stack(GRID, None, 58000.0, seed=100 + seed)
    assert centroid.measure(st, (120.0, 120.0), PIX, RADIUS) is None


def test_centroid_does_not_follow_a_shifted_prediction() -> None:
    # Validation found an earlier method that returned the prediction: moving it 15 arcsec
    # moved the answer 13.7 arcsec. Here the answer must stay put.
    truth = (120.5, 118.2)
    st = gaussian_stack(GRID, truth, 58000.0, amp=20.0, seed=7)
    a = centroid.measure(st, truth, PIX, RADIUS)
    shift_arcsec = 15.0
    b = centroid.measure(st, (truth[0] + shift_arcsec / PIX, truth[1]), PIX, RADIUS)
    assert a is not None and b is not None
    moved = np.hypot(b.x - a.x, b.y - a.y) * PIX
    assert moved / shift_arcsec < 0.05


def _two_sources(sep_px: float):
    st = gaussian_stack(GRID, (110.5, 120.5), 58000.0, amp=30.0, seed=8)
    other = gaussian_stack(GRID, (110.5 + sep_px, 120.5), 58000.0, amp=30.0, background=0.0,
                           noise=0.0)
    return replace(st, image=st.image + other.image)


def test_centroid_prefers_nearest_peak_and_warns_when_close() -> None:
    c = centroid.measure(_two_sources(10.0), (112.0, 120.0), PIX, RADIUS)
    assert c is not None and abs(c.x - 110.5) < 0.5
    assert any("within two PSF widths" in w for w in c.warnings)


def test_no_ambiguity_warning_for_a_distant_field_star() -> None:
    # Real SPHEREx views put a field star inside the 50" search disc of nearly every
    # frame; that is not ambiguity and must not warn.
    c = centroid.measure(_two_sources(25.0), (113.0, 120.0), PIX, RADIUS)
    assert c is not None and abs(c.x - 110.5) < 0.5 and c.warnings == ()


def test_centroid_skips_a_known_field_star_when_the_target_is_not_there() -> None:
    # WISE 0855 at 1.6 um: invisible, with a Gaia star 6.5 px from the prediction. Before
    # the fix the centroid locked onto the star (|d| 6.5-10.7 px in 5 real frames).
    st = gaussian_stack(GRID, (130.0, 120.5), 58000.0, amp=30.0, seed=9)
    assert centroid.measure(st, (123.5, 120.5), PIX, RADIUS) is not None
    c, notes = centroid.detect(st, (123.5, 120.5), PIX, RADIUS, avoid_px=[(130.2, 120.4)])
    assert c is None and notes == (centroid.ON_KNOWN_STAR,)


def test_known_star_does_not_block_a_target_at_the_prediction() -> None:
    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=30.0, seed=10)
    c = centroid.measure(st, (120.8, 120.2), PIX, RADIUS, avoid_px=[(126.0, 120.5)])
    assert c is not None and abs(c.x - 120.5) < 0.5


def _floored(native: float, reg: float) -> float:
    return math.hypot(centroid.ERR_FLOOR_NATIVE_PX * native, reg)


def test_centroid_error_has_a_measurement_floor_plus_registration() -> None:
    # Eps Ind B: bright stacks gave 0.006" before, against 0.1-0.2" real per-epoch scatter.
    st = replace(gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=5000.0, seed=11, native=6.15,
                                fwhm_arcsec=10.0, mission="SPHEREx"), band="spx-b6")
    c = centroid.measure(st, (120.5, 120.5), PIX, RADIUS)
    floor = _floored(6.15, centroid.REG_FLOOR_ARCSEC[("SPHEREx", None)])
    assert c is not None and c.err_arcsec == pytest.approx(floor, rel=1e-3)


def test_a_saturated_flag_alone_does_not_change_the_method() -> None:
    # The stack-level "saturated" warning reaches the frame from Stack.warnings; the centroid
    # adds its own note only when it measured a saturated core from the wings.
    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=30.0, warnings=("saturated",))
    c = centroid.measure(st, (121.0, 120.0), PIX, RADIUS)
    assert c is not None and c.method == "psf"
    assert centroid.SATURATED_NOTE not in c.warnings


@pytest.mark.parametrize("xy", [(238.5, 120.5), (120.5, 238.5), (1.5, 120.5), (120.5, 1.5),
                                (238.5, 238.5)])
def test_centroid_near_every_edge_does_not_crash(xy) -> None:
    # Code review R1: the fit window was clipped only at 0, so a source within a few pixels
    # of the right or bottom edge raised IndexError and aborted the build.
    st = gaussian_stack(GRID, xy, 58000.0, amp=40.0, seed=12)
    c = centroid.measure(st, xy, PIX, RADIUS)
    assert c is None or np.hypot(c.x - xy[0], c.y - xy[1]) < 2.0


def test_very_bright_source_has_a_nonzero_error_that_survives_the_manifest() -> None:
    # Code review R2: a formal error of 1e-4" rounded to 0.0 and failed validation.
    from pxs.manifest import frame_entry

    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=2e4, seed=13)
    c = centroid.measure(st, (120.5, 120.5), PIX, RADIUS)
    entry = frame_entry("f", "W2", st, "f.png", (120.5, 120.5), c)
    floor = _floored(st.native_pixscale_arcsec, centroid.REG_FLOOR_ARCSEC[("WISE", "W2")])
    assert entry["centroid_err_arcsec"] == pytest.approx(floor, abs=1e-3)


@pytest.mark.parametrize("seed", range(4))
def test_faint_target_beside_a_brighter_star_is_still_a_peak(seed: int) -> None:
    # CWISE J2112-0529, W2 2010: target S/N about 6 at the prediction, a star 12" away. The
    # star's flank 8-9 px from the target is higher than the target's own peak, so a peak
    # test over a 17 px box took the target for part of the star.
    st = gaussian_stack(GRID, (111.5, 128.5), 58000.0, amp=3.0, fwhm_arcsec=7.3, seed=seed)
    i, j = np.mgrid[: GRID.size_px, : GRID.size_px]
    s = 7.3 / 2.3548 / PIX
    faint = 1.6 * np.exp(-((j + 0.5 - 120.5) ** 2 + (i + 0.5 - 120.0) ** 2) / (2 * s * s))
    st = replace(st, image=(st.image + faint).astype(np.float32))
    c, notes = centroid.detect(st, (120.5, 120.0), PIX, RADIUS, avoid_px=[(111.5, 128.5)])
    assert c is not None and math.hypot(c.x - 120.5, c.y - 120.0) < 1.5, notes


def _pair(seed: int, target_amp: float | None) -> tuple:
    # CWISE J2112-0529 in four-visit W2 stacks: target S/N about 9, a star 10.5" away at
    # S/N about 17. Smoothed with the PSF they make one ridge, so the target is no peak.
    st = gaussian_stack(GRID, (113.0, 127.5), 58000.0, amp=3.0, fwhm_arcsec=7.3, seed=seed)
    if target_amp is not None:
        i, j = np.mgrid[: GRID.size_px, : GRID.size_px]
        s = 7.3 / 2.3548 / PIX
        st = replace(st, image=(st.image + target_amp * np.exp(
            -((j + 0.5 - 118.0) ** 2 + (i + 0.5 - 118.5) ** 2) / (2 * s * s))).astype(np.float32))
    return centroid.detect(st, (118.0, 118.5), PIX, 15.0, avoid_px=[(113.0, 127.5)])


@pytest.mark.parametrize("seed", range(4))
def test_target_merged_with_a_known_star_is_found_after_removing_the_star(seed: int) -> None:
    c, notes = _pair(seed, 1.7)
    assert c is not None and math.hypot(c.x - 118.0, c.y - 118.5) < 1.5, notes
    if seed in (0, 1, 3):  # these need the star removed first; with seed 2 the noise helps
        assert centroid.STAR_REMOVED in c.warnings


@pytest.mark.parametrize("seed", range(4))
def test_a_known_star_alone_is_still_not_the_target(seed: int) -> None:
    c, notes = _pair(seed, None)
    assert c is None and notes == (centroid.ON_KNOWN_STAR,)


@pytest.mark.parametrize("seed", range(4))
def test_a_bright_star_is_not_removed_so_its_residual_is_no_target(seed: int) -> None:
    # CWISE J2021+1524: a G = 11.6 star 13" away. A Gaussian never fits a real bright PSF
    # well, so what is left after subtracting it is not evidence of a faint target.
    st = gaussian_stack(GRID, (113.0, 127.5), 58000.0, amp=200.0, fwhm_arcsec=7.3, seed=seed)
    yy, xx = np.mgrid[: GRID.size_px, : GRID.size_px] + 0.5
    halo = 6.0 * np.exp(-np.hypot(xx - 113.0, yy - 127.5) / 6.0)  # non-Gaussian wings
    st = replace(st, image=(st.image + halo).astype(np.float32))
    c, notes = centroid.detect(st, (118.0, 118.5), PIX, 15.0, avoid_px=[(113.0, 127.5)])
    assert c is None and notes == (centroid.ON_KNOWN_STAR,)


@pytest.mark.parametrize("seed", range(4))
def test_one_bright_source_gives_one_peak(seed: int) -> None:
    st = gaussian_stack(GRID, (120.5, 120.5), 58000.0, amp=200.0, fwhm_arcsec=7.3, seed=seed)
    fr = centroid._prepare(st, PIX)
    assert len(centroid._peaks(fr, (120.5, 120.5), 30.0, centroid.SNR_MIN)) == 1
