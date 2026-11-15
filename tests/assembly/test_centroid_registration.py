"""Search radius per mission, registration against field stars, and error floors."""

import math
from dataclasses import replace

import numpy as np
import pytest
from build_fakes import GRID

from pxs import centroid
from pxs.grid import Stack

PIX = GRID.pixscale_arcsec
STARS = [(40.5, 50.5), (190.5, 60.5), (60.5, 180.5), (200.5, 200.5), (120.5, 40.5),
         (30.5, 120.5)]


def field(band: str, shift_px: tuple[float, float], target=(120.3, 119.8), seed: int = 0,
          stars=STARS) -> Stack:
    """Target plus field stars, every source drawn `shift_px` from its catalogue position
    (a frame registration error)."""
    rng = np.random.default_rng(seed)
    img = 3.0 + rng.standard_normal(GRID.shape)
    i, j = np.mgrid[: GRID.size_px, : GRID.size_px]
    s = 6.7 / 2.3548
    for x, y in [target, *stars]:
        xs, ys = x + shift_px[0], y + shift_px[1]
        img += 200.0 * np.exp(-((j + 0.5 - xs) ** 2 + (i + 0.5 - ys) ** 2) / (2 * s * s))
    return Stack(image=img.astype(np.float32), mission="WISE", band=band,
                 wavelength_um=(3.0, 3.8) if band == "W1" else (4.0, 5.2), mjd=58000.0,
                 date_span_days=1.0, n_exposures=12, native_pixscale_arcsec=2.75)


def test_w1_frame_offset_is_measured_on_field_stars_and_removed() -> None:
    shift = (0.4, -0.25)  # px; W1 frames sit up to 0.6" off in alternate visits
    c, _ = centroid.detect(field("W1", shift), (120.0, 120.0), PIX, 20.0, avoid_px=STARS)
    assert c is not None and c.n_reference_stars == len(STARS)
    assert c.registration_px == pytest.approx(shift, abs=0.03)
    assert (c.x, c.y) == pytest.approx((120.3, 119.8), abs=0.03)
    assert any(w.startswith(f"registered to {len(STARS)} Gaia stars") for w in c.warnings)
    floor = math.hypot(centroid.ERR_FLOOR_NATIVE_PX * 2.75, centroid.REG_RESIDUAL_ARCSEC)
    assert c.err_arcsec >= floor


def test_w2_is_not_corrected_and_carries_its_floor_instead() -> None:
    c, _ = centroid.detect(field("W2", (0.4, -0.25)), (120.0, 120.0), PIX, 20.0, avoid_px=STARS)
    assert c is not None and c.n_reference_stars == 0 and c.registration_px == (0.0, 0.0)
    assert (c.x, c.y) == pytest.approx((120.7, 119.55), abs=0.03)
    assert c.err_arcsec >= centroid.REG_FLOOR_ARCSEC[("WISE", "W2")]


def test_too_few_reference_stars_means_no_correction_and_the_w1_floor() -> None:
    st = field("W1", (0.4, -0.25), stars=STARS[:2])
    c, _ = centroid.detect(st, (120.0, 120.0), PIX, 20.0, avoid_px=STARS[:2])
    assert c is not None and c.n_reference_stars == 0
    assert c.err_arcsec >= centroid.REG_FLOOR_ARCSEC[("WISE", "W1")]


def test_blended_reference_stars_are_not_used() -> None:
    pairs = [*STARS, (STARS[0][0] + 5.0, STARS[0][1])]  # a pair 5" apart: neither is isolated
    c, _ = centroid.detect(field("W1", (0.0, 0.0), stars=pairs), (120.0, 120.0), PIX, 20.0,
                           avoid_px=pairs)
    assert c is not None and c.n_reference_stars == len(STARS) - 1


def test_psf_width_depends_on_mission_and_band() -> None:
    st = field("W2", (0, 0))
    assert centroid.psf_fwhm_arcsec(st) == 7.3
    assert centroid.psf_fwhm_arcsec(replace(st, band="W1")) == 6.7
    spx = replace(st, mission="SPHEREx", band="spx-b6", wavelength_um=(4.42, 5.0),
                  native_pixscale_arcsec=6.15)
    assert centroid.psf_fwhm_arcsec(spx) == 10.0
    assert centroid.psf_fwhm_arcsec(replace(spx, wavelength_um=(1.1, 1.65))) == 9.0


def test_search_radius_follows_the_prediction_uncertainty() -> None:
    fwhm = 10.0
    still = centroid.search_radius_arcsec(fwhm, 0.0, 10.0)
    known = centroid.search_radius_arcsec(fwhm, 2000.0, 10.0)
    unknown = centroid.search_radius_arcsec(fwhm, None, 10.0)
    with_plx = centroid.search_radius_arcsec(fwhm, 2000.0, 10.0, parallax_mas=500.0)
    assert still < known < unknown
    assert with_plx == pytest.approx(known + centroid.SEARCH_SIGMA * 0.5)
    assert centroid.search_radius_arcsec(fwhm, None, 30.0) == centroid.MAX_SEARCH_FWHM * fwhm
    # The audit's M1: 41" on SPHEREx for a static source; now 2 FWHM plus a little.
    assert still < 25.0


def test_centroid_does_not_follow_a_shifted_prediction_with_registration_on() -> None:
    st = field("W1", (0.2, 0.1), seed=3)
    a = centroid.measure(st, (120.3, 119.8), PIX, 20.0, avoid_px=STARS)
    b = centroid.measure(st, (129.3, 113.8), PIX, 20.0, avoid_px=STARS)
    assert a is not None and b is not None
    assert math.hypot(b.x - a.x, b.y - a.y) * PIX < 0.02
