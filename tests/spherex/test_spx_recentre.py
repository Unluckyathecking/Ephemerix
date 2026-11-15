"""Per-pass recentring of the forced photometry, and the per-detector error scale (B3)."""

from dataclasses import replace

import numpy as np
import pytest

from pxs.spherex import config
from pxs.spherex.photometry import measure, psf_model
from pxs.spherex.recentre import fit_offset, pixel_offset, sky_to_pixel_jacobian
from pxs.spherex.spectrum import detector_scales, recentre_pass, to_points

from .conftest import synthetic_stamp, tan_header

N = 31
PIX = config.PIXSCALE_ARCSEC
RA, DEC = 150.0, 2.0


def _stamp(psf, amp, east, north, *, rot=30.0, detector=6, seed=1, sigma=0.01):
    """Noise (sigma MJy/sr) plus amp x PSF placed `east`, `north` arcsec from the target."""
    blank = synthetic_stamp(np.zeros((N, N)), psf=psf, detector=detector, ra=RA, dec=DEC)
    blank = replace(blank, header=tan_header(RA, DEC, (1001.0, 1001.0), rot_deg=rot,
                                             detector=detector))
    dx, dy = pixel_offset(blank, east, north)
    model = amp * psf_model(blank, blank.xpix + dx, blank.ypix + dy)
    noise = np.random.default_rng(seed).normal(0, sigma, (N, N))
    image = noise + model + blank.zodi
    return replace(blank, image=image, variance=np.full((N, N), sigma**2))


def _pass(psf, amp, east, north, detectors=(1, 2, 3, 4, 5, 6), per=2, **kw):
    out = []
    for i, d in enumerate(detectors):
        for k in range(per):
            rot = 30.0 + 150.0 * (k % 2)  # two roll angles, as in two survey seasons
            out.append(_stamp(psf, amp, east, north, rot=rot, detector=d, seed=10 * i + k, **kw))
    return out


def test_jacobian_follows_the_roll(gaussian_psf) -> None:
    s = _stamp(gaussian_psf, 0.0, 0.0, 0.0, rot=30.0)
    j = sky_to_pixel_jacobian(s)
    assert np.hypot(*j[:, 0]) == pytest.approx(1 / PIX, rel=1e-3)
    assert np.degrees(np.arctan2(j[1, 0], -j[0, 0])) == pytest.approx(30.0, abs=0.5)


def test_a_point_three_pixel_miss_is_found_and_the_flux_recovered(gaussian_psf) -> None:
    east = 0.3 * PIX
    stamps = _pass(gaussian_psf, 2.0, east, 0.0)
    rc = fit_offset(stamps, 1.0)
    assert rc.applied and rc.reason == ""
    assert rc.east_arcsec == pytest.approx(east, abs=0.1)
    assert rc.north_arcsec == pytest.approx(0.0, abs=0.1)
    assert 0 < rc.err_east_arcsec < 0.3
    true = 2.0 * config.MJYSR_TO_MJY
    fixed = np.median([p.flux_mjy for p in to_points(stamps)])
    moved = np.median([p.flux_mjy for p in to_points(stamps, (rc.east_arcsec, rc.north_arcsec))])
    assert fixed < 0.96 * true  # this Gaussian is broader than the real ePSF
    assert moved == pytest.approx(true, rel=0.02)


def test_points_report_the_offset(gaussian_psf, monkeypatch) -> None:
    rc = recentre_pass(_pass(gaussian_psf, 2.0, 0.6, -0.6))
    assert rc.applied
    d = rc.as_dict()
    assert d["applied"] and d["err_east_arcsec"] > 0 and d["reason"] == ""


def test_too_faint_is_left_alone(gaussian_psf) -> None:
    rc = fit_offset(_pass(gaussian_psf, 0.02, 0.3 * PIX, 0.0), 1.0)
    assert not rc.applied and rc.reason == "too faint to locate"


def test_an_offset_at_the_limit_is_refused(gaussian_psf) -> None:
    # 0.9 px away with no catalogue: beyond the 0.5 px safe limit.
    rc = fit_offset(_pass(gaussian_psf, 2.0, 0.9 * PIX, 0.0), 1.0)
    assert not rc.applied and rc.reason == "offset reached the limit"


def test_with_neighbours_known_the_limit_is_one_pixel(gaussian_psf) -> None:
    rc = fit_offset(_pass(gaussian_psf, 2.0, 0.7 * PIX, 0.0), 1.0, neighbours=[],
                    target_sky=(RA, DEC))
    assert rc.applied and rc.east_arcsec == pytest.approx(0.7 * PIX, abs=0.15)


def test_never_recentres_next_to_a_catalogued_neighbour(gaussian_psf) -> None:
    stamps = _pass(gaussian_psf, 2.0, 0.3 * PIX, 0.0)
    near = (RA + 1.5 * PIX / 3600 / np.cos(np.radians(DEC)), DEC)  # 1.5 px east
    rc = fit_offset(stamps, 1.0, neighbours=[near], target_sky=(RA, DEC))
    assert not rc.applied and rc.reason == "catalogued neighbour nearby"
    far = (RA + 3.0 * PIX / 3600 / np.cos(np.radians(DEC)), DEC)  # 3 px east
    rc = fit_offset(stamps, 1.0, neighbours=[far], target_sky=(RA, DEC))
    assert not rc.applied and rc.reason == "offset points towards a neighbour"
    west = (RA - 3.0 * PIX / 3600 / np.cos(np.radians(DEC)), DEC)
    assert fit_offset(stamps, 1.0, neighbours=[west], target_sky=(RA, DEC)).applied


def test_short_and_long_arrays_that_disagree_are_refused(gaussian_psf) -> None:
    blue = _pass(gaussian_psf, 2.0, 0.4 * PIX, 0.0, detectors=(1, 2, 3))
    red = _pass(gaussian_psf, 2.0, -0.1 * PIX, 0.0, detectors=(4, 5, 6))
    rc = fit_offset(blue + red, 1.0)
    assert not rc.applied and rc.reason == "offset differs between short and long wavelengths"


def test_inputs_are_not_modified(gaussian_psf) -> None:
    stamps = _pass(gaussian_psf, 2.0, 0.3 * PIX, 0.0)
    before = [(s.xpix, s.ypix, s.image.copy()) for s in stamps]
    fit_offset(stamps, 1.0)
    to_points(stamps, (1.0, 0.0))
    for s, (x, y, img) in zip(stamps, before):
        assert (s.xpix, s.ypix) == (x, y) and np.array_equal(s.image, img)


def test_detector_with_few_samples_takes_the_measured_pass_scale(gaussian_psf) -> None:
    # Code review B3: 4 stamps on D1 (32 empty samples < 40) used to get the constant 1.5.
    # Pure noise everywhere, so the measured pass-wide scale is about 1.
    stamps = [_stamp(gaussian_psf, 0.0, 0.0, 0.0, detector=1, seed=s) for s in range(4)]
    stamps += [_stamp(gaussian_psf, 0.0, 0.0, 0.0, detector=2, seed=100 + s) for s in range(8)]
    scales = detector_scales(stamps)
    assert scales[1] != config.ERROR_SCALE
    assert scales[1] == pytest.approx(1.0, abs=0.3)


def test_empty_positions_are_fixed_on_the_sky(gaussian_psf) -> None:
    # A star 8 px east on the sky lands on the same empty position whatever the roll.
    star_east = 8 * PIX
    a = _stamp(gaussian_psf, 2.0, star_east, 0.0, rot=30.0)
    b = _stamp(gaussian_psf, 2.0, star_east, 0.0, rot=200.0)
    ea, eb = (to_points([s])[0].empty_mjy for s in (a, b))
    assert int(np.nanargmax(ea)) == int(np.nanargmax(eb))
    assert measure(a).flux_mjy == pytest.approx(0.0, abs=0.05)


def test_extract_spectrum_applies_and_reports_the_offset(gaussian_psf, monkeypatch) -> None:
    from pxs.spherex import spectrum
    from pxs.spherex.stamps import Batch
    from pxs.spherex.types import Frame, Pass, Target

    stamps = _pass(gaussian_psf, 2.0, 0.3 * PIX, 0.0)
    frames = tuple(Frame("c", f"o{i}", s.detector, 61000.0 + i, "k", 0.7, 5.0)
                   for i, s in enumerate(stamps))
    monkeypatch.setattr(spectrum, "read_many",
                        lambda jobs, *a, **k: Batch(tuple(zip(frames, stamps)), 0, 0))
    pts = spectrum.extract_spectrum(Pass(frames), Target("X", RA, DEC, 2016.0))
    assert pts.recentre.applied
    assert pts.recentre.east_arcsec == pytest.approx(0.3 * PIX, abs=0.1)
    assert np.median([p.flux_mjy for p in pts]) == pytest.approx(
        2.0 * config.MJYSR_TO_MJY, rel=0.02)
