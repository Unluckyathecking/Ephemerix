"""Sky motion of a distant planet as SPHEREx sees it (about 90 deg from the Sun)."""

from __future__ import annotations

import pytest

from pxs.planetx import motion


@pytest.mark.parametrize("r, parallax, orbital", [
    # arcmin between passes six months apart
    (300, 22.9, 2.1), (400, 17.2, 1.4), (500, 13.8, 1.0), (700, 9.8, 0.6), (1000, 6.9, 0.3),
])
def test_shift_between_passes_matches_the_audit(r, parallax, orbital):
    p, o = motion.shift_between_passes_arcmin(r)
    assert p == pytest.approx(parallax, abs=0.05)
    assert o == pytest.approx(orbital, abs=0.05)


def test_rate_at_500_au_by_hand():
    # At the ecliptic pole the whole of Earth's 29.78 km/s is across the line of sight;
    # add the planet's circular speed 29.78 / sqrt(500) = 1.33 km/s (upper bound):
    # 31.11 km/s * 86400 s / (500 * 1.496e8 km) = 3.594e-5 rad = 7.41 arcsec per day.
    assert motion.rate_arcsec_per_day(500, beta_deg=90) == pytest.approx(7.41, abs=0.02)


def test_rate_in_the_ecliptic_is_orbital_only():
    # 1.33 km/s at 500 au: 0.317 arcsec per day.
    assert motion.rate_arcsec_per_day(500, beta_deg=0) == pytest.approx(0.317, abs=0.003)


def test_rate_matches_fortney_2016_wise_epoch_estimate():
    # Fortney et al. 2016 (ApJL 824, L25): 0.12 arcsec/hr at 622 au near RA 2h, Dec -20
    # (ecliptic latitude -30 deg), seen by WISE at 90 deg elongation.
    assert motion.rate_arcsec_per_day(622, beta_deg=-30) == pytest.approx(0.12 * 24, rel=0.1)


def test_smear_in_one_pass_in_the_ecliptic_is_a_few_arcsec():
    # Orbital 0.317 "/day * 14 d = 4.4" plus parallax curvature 412.5" * (1 - cos(2 pi 7/365.25))
    # = 3.0"; total about 7.4" (1.2 SPHEREx pixels) at 500 au.
    assert motion.smear_in_pass_arcsec(500, beta_deg=0, days=14) == pytest.approx(7.4, abs=0.2)


def test_pixels():
    assert motion.to_pixels(6.15) == pytest.approx(1.0)
