"""Saturated stars: centroid from the wings, white cores in the rendering (synthetic data)."""

from dataclasses import replace

import numpy as np
import pytest
from build_fakes import GRID

from pxs import centroid, render
from pxs.grid import Stack

PIX = GRID.pixscale_arcsec
SAT_LEVEL = 400.0


def _psf(xy: tuple[float, float], amp: float) -> np.ndarray:
    """Moffat core with point-symmetric diffraction spikes, like the WISE PSF."""
    i, j = np.mgrid[: GRID.size_px, : GRID.size_px]
    dx, dy = j + 0.5 - xy[0], i + 0.5 - xy[1]
    r2 = dx**2 + dy**2
    core = (1.0 + r2 / 4.0**2) ** -2.5
    spikes = 0.004 * np.exp(-np.minimum(np.abs(dx - dy), np.abs(dx + dy)) ** 2 / 2.0) / (
        1.0 + r2 / 30.0**2)
    return amp * (core + spikes)


def saturated_stack(xy, *, mode: str, ragged: int = 0, seed: int = 0, amp: float = 2e4,
                    mission: str = "WISE", native: float = 2.75) -> Stack:
    """A saturated star. mode "nan": the core is NaN (SPHEREx); "plateau": the core is a flat
    fill flagged in saturated_mask (WISE combine). `ragged` adds that many extra flagged
    pixels on one side of the core, like the off-centre masks of late NEOWISE visits."""
    rng = np.random.default_rng(seed)
    img = 5.0 + _psf(xy, amp) + rng.standard_normal(GRID.shape)
    core = img > SAT_LEVEL
    if ragged:
        ys, xs = np.nonzero(core)
        extra = np.zeros_like(core)
        extra[ys.max() + 1: ys.max() + 1 + ragged, xs.min(): xs.max() + 1] = True
        core |= extra
    mask = None
    if mode == "nan":
        img[core] = np.nan
    else:
        img[core] = SAT_LEVEL * 1.2
        mask = core
    band = "W2" if mission == "WISE" else "spx-b6"
    return Stack(image=img.astype(np.float32), mission=mission, band=band,
                 wavelength_um=(4.0, 5.2) if mission == "WISE" else (4.42, 5.0), mjd=58000.0,
                 date_span_days=1.0, n_exposures=12, native_pixscale_arcsec=native,
                 saturated_mask=mask)


@pytest.mark.parametrize("mode", ["nan", "plateau"])
@pytest.mark.parametrize("seed", range(3))
def test_saturated_centroid_comes_from_the_wings(mode: str, seed: int) -> None:
    truth = (118.37 + seed * 0.31, 121.82 - seed * 0.17)
    st = saturated_stack(truth, mode=mode, seed=seed)
    c, notes = centroid.detect(st, (120.0, 120.0), PIX, 20.0)
    assert c is not None and notes == ()
    assert c.method == "wings" and centroid.SATURATED_NOTE in c.warnings
    assert np.hypot(c.x - truth[0], c.y - truth[1]) * PIX < 0.1


def test_ragged_off_centre_mask_does_not_drag_the_centroid() -> None:
    # Barnard's Star in late NEOWISE visits: the flagged core extends 4" to one side.
    truth = (120.4, 119.6)
    st = saturated_stack(truth, mode="plateau", ragged=4, seed=5)
    c = centroid.measure(st, (121.0, 121.0), PIX, 20.0)
    assert c is not None and np.hypot(c.x - truth[0], c.y - truth[1]) * PIX < 0.15


def test_saturated_error_reflects_the_method() -> None:
    st = saturated_stack((120.2, 120.7), mode="nan", mission="SPHEREx", native=6.15)
    c = centroid.measure(st, (120.0, 120.0), PIX, 30.0)
    expected = np.hypot(centroid.SATURATED_ERR_NATIVE_PX * 6.15,
                        centroid.REG_FLOOR_ARCSEC[("SPHEREx", None)])
    assert c is not None and c.err_arcsec == pytest.approx(expected, rel=1e-3)


def test_saturated_centroid_does_not_follow_a_shifted_prediction() -> None:
    truth = (119.6, 120.3)
    st = saturated_stack(truth, mode="plateau", seed=6)
    a = centroid.measure(st, truth, PIX, 20.0)
    b = centroid.measure(st, (truth[0] + 8.0, truth[1] - 5.0), PIX, 20.0)
    assert a is not None and b is not None
    assert np.hypot(b.x - a.x, b.y - a.y) * PIX < 0.02


def test_saturated_core_renders_white_and_does_not_set_the_stretch() -> None:
    st = saturated_stack((120.5, 120.5), mode="nan", seed=7)
    filled = replace(st, image=np.where(np.isfinite(st.image), st.image, 1e7).astype(np.float32),
                     saturated_mask=~np.isfinite(st.image))
    px = render.to_uint8(st, render.shared_stretch([st]))
    assert px[120, 120] == 255  # not the background grey of a no-data hole
    # A huge fill value in the flagged core does not move the white point.
    assert render.shared_stretch([filled]).white == pytest.approx(
        render.shared_stretch([st]).white, rel=1e-3)


def test_flagged_cluster_on_faint_sky_is_not_whitened() -> None:
    # Code review R7: a persistent bad-pixel cluster must not become a white fake star.
    rng = np.random.default_rng(8)
    img = (5.0 + rng.standard_normal(GRID.shape)).astype(np.float32)
    img[60:64, 60:64] = np.nan
    mask = ~np.isfinite(img)
    st = Stack(image=img, mission="WISE", band="W2", wavelength_um=(4.0, 5.2), mjd=58000.0,
               date_span_days=1.0, n_exposures=4, native_pixscale_arcsec=2.75,
               saturated_mask=mask)
    assert not render.saturated_cores(st).any()
    px = render.to_uint8(st, render.shared_stretch([st]))
    assert px[61, 61] < 120
    assert centroid.measure(st, (62.0, 62.0), PIX, 20.0) is None
