from dataclasses import replace

import numpy as np
import pytest

from pxs.spherex import config
from pxs.spherex.photometry import error_scale, good_mask, measure, psf_model
from pxs.spherex.read import read_stamp
from pxs.spherex.spectrum import to_points

from .conftest import synthetic_stamp

BIT = config.FLAG_BITS
N = 31


def _source(psf: np.ndarray, amp: float, seed: int = 1, x: float = 1000.3, y: float = 999.8):
    """Stamp with Gaussian noise (sigma 0.01 MJy/sr) and amp x PSF at sub-pixel (x, y)."""
    blank = replace(synthetic_stamp(np.zeros((N, N)), psf=psf), xpix=x, ypix=y)
    model = amp * psf_model(blank, x, y)
    noise = np.random.default_rng(seed).normal(0, 0.01, (N, N))
    return replace(synthetic_stamp(noise + model + 0.003, psf=psf), xpix=x, ypix=y)


def test_source_flag_is_never_masked() -> None:
    flags = np.zeros((N, N), np.int32)
    flags[:, :] = 1 << BIT["SOURCE"]
    flags[0, 0] |= 1 << BIT["HOT"]
    flags[1, 1] = 1 << BIT["HALO"]
    image = np.zeros((N, N))
    image[2, 2] = np.nan
    good = good_mask(synthetic_stamp(image, flags=flags))
    assert not good[0, 0] and not good[2, 2]
    assert good[1, 1] and good.sum() == N * N - 2


@pytest.mark.parametrize("name", list(config._BAD_NAMES))
def test_each_bad_bit_masks(name: str) -> None:
    flags = np.zeros((N, N), np.int32)
    flags[3, 4] = 1 << BIT[name]
    assert not good_mask(synthetic_stamp(np.zeros((N, N)), flags=flags))[3, 4]


def test_bad_mask_excludes_source() -> None:
    assert not config.BAD_MASK & (1 << BIT["SOURCE"])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_recovers_injected_flux(gaussian_psf, seed: int) -> None:
    amp = 2.0
    m = measure(_source(gaussian_psf, amp, seed))
    true = amp * config.MJYSR_TO_MJY
    assert m.ok
    assert abs(m.flux_mjy - true) < 2 * m.err_mjy
    assert m.err_mjy < 0.1 * true


def test_recovers_injected_flux_with_real_epsf(offline_store, recorded, gaussian_psf) -> None:
    rec = recorded["eps_d6"]
    psf = read_stamp(offline_store, rec["key"], rec["ra"], rec["dec"], half=rec["half"]).psf
    assert psf.sum() == pytest.approx(1.0, abs=0.05)
    m = measure(_source(psf, 2.0))
    assert abs(m.flux_mjy - 2.0 * config.MJYSR_TO_MJY) < 2 * m.err_mjy


def test_saturated_core_gives_flagged_point(gaussian_psf) -> None:
    s = _source(gaussian_psf, 50.0)
    flags = np.zeros((N, N), np.int32)
    flags[15, 15] = 1 << BIT["OVERFLOW"]
    (p,) = to_points([replace(s, flags=flags)])
    assert p.flagged and p.reason == "saturated"
    assert np.isnan(p.flux_mjy) and np.isnan(p.err_mjy)


def test_nan_core_is_saturated(gaussian_psf) -> None:
    s = _source(gaussian_psf, 50.0)
    image = s.image.copy()
    image[15, 15] = np.nan
    assert measure(replace(s, image=image)).reason == "saturated"


def test_sur_error_alone_is_masked_not_saturated(gaussian_psf) -> None:
    s = _source(gaussian_psf, 2.0)
    flags = np.zeros((N, N), np.int32)
    flags[15, 15] = 1 << BIT["SUR_ERROR"]
    m = measure(replace(s, flags=flags))
    assert m.ok and abs(m.flux_mjy - 2.0 * config.MJYSR_TO_MJY) < 3 * m.err_mjy


def test_mostly_masked_psf_is_flagged_masked(gaussian_psf) -> None:
    s = _source(gaussian_psf, 2.0)
    yy, xx = np.mgrid[0:N, 0:N]
    flags = np.where(np.hypot(xx - 15.3, yy - 14.8) <= 3, 1 << BIT["HOT"], 0).astype(np.int32)
    flags[15, 15] = 0  # one good pixel left in the core
    assert measure(replace(s, flags=flags)).reason == "masked"


def test_off_detector_core_is_masked(gaussian_psf) -> None:
    s = _source(gaussian_psf, 2.0)
    flags = np.zeros((N, N), np.int32)
    flags[15, 15] = config.MISSING_MASK
    assert measure(replace(s, flags=flags)).reason == "masked"


def test_real_saturated_star_is_flagged(offline_store, recorded) -> None:
    rec = recorded["barnard"]
    s = read_stamp(offline_store, rec["key"], rec["ra"], rec["dec"], half=rec["half"])
    assert measure(s).reason == "saturated"


def test_error_scale_is_one_for_pure_noise(gaussian_psf) -> None:
    stamps = [_source(gaussian_psf, 0.0, seed) for seed in range(10)]
    assert error_scale(stamps) == pytest.approx(1.0, abs=0.25)


def test_error_scale_grows_with_unmodelled_noise(gaussian_psf) -> None:
    stamps = [_source(gaussian_psf, 0.0, seed) for seed in range(10)]
    noisier = [replace(s, image=s.zodi + 3 * (s.image - s.zodi)) for s in stamps]
    assert error_scale(noisier) == pytest.approx(3.0, rel=0.25)
