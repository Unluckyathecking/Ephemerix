"""Blend warning against a synthetic Gaia catalogue."""

from pxs.blend import blend_blocks_typing, blend_warnings, is_target, pass_years
from pxs.target import Target

T = Target("Mover", 100.0, 10.0, 2016.0, pmra_masyr=2000.0, pmdec_masyr=0.0)
YEARS = [2025.5, 2026.3]
COS = 0.984807753  # cos(10 deg)


def _src(dra_arcsec: float, ddec_arcsec: float, g: float | None = 15.0, epoch: float = 2016.0,
         pm=(0.0, 0.0), year: float = 2025.5) -> dict:
    """Gaia source placed (dra, ddec) arcsec from the target's position at `year`."""
    ra0 = 100.0 + 2000.0 * (year - 2016.0) / 3.6e6 / COS
    return {"id": "x", "ra": ra0 + dra_arcsec / 3600.0 / COS, "dec": 10.0 + ddec_arcsec / 3600.0,
            "epoch": epoch, "pmra_masyr": pm[0], "pmdec_masyr": pm[1], "g_mag": g}


def test_star_within_one_pixel_is_reported_with_g_and_separation() -> None:
    (w,) = blend_warnings(T, [_src(0.0, 4.0, g=14.25)], YEARS)
    assert "G = 14.2" in w and "4.0 arcsec" in w


def test_star_beyond_one_pixel_is_not_reported() -> None:
    assert blend_warnings(T, [_src(0.0, 7.0)], YEARS) == []


def test_closest_approach_over_all_epochs_counts() -> None:
    # Near the target only at the second epoch.
    assert len(blend_warnings(T, [_src(0.0, 3.0, year=2026.3)], YEARS)) == 1


def test_target_itself_in_gaia_is_not_a_blend() -> None:
    me = {"id": "t", "ra": 100.0, "dec": 10.0, "epoch": 2016.0, "pmra_masyr": 1990.0,
          "pmdec_masyr": 5.0, "g_mag": 12.0}
    assert is_target(T, me) and blend_warnings(T, [me], YEARS) == []


def test_unrelated_star_at_the_target_2016_position_is_a_blend_later_only_if_close() -> None:
    # Fixed star where the target was in 2016: same place but different motion, so not
    # the target; by 2025 the target is 19" away, so no blend either.
    fixed = {"id": "f", "ra": 100.0, "dec": 10.0, "epoch": 2016.0, "pmra_masyr": 0.0,
             "pmdec_masyr": 0.0, "g_mag": 18.0}
    assert not is_target(T, fixed) and blend_warnings(T, [fixed], YEARS) == []


def test_missing_magnitude_and_proper_motion() -> None:
    src = {**_src(2.0, 0.0), "g_mag": None, "pmra_masyr": None, "pmdec_masyr": None}
    (w,) = blend_warnings(T, [src], YEARS)
    assert "unknown G magnitude" in w


def test_no_epochs_no_warning() -> None:
    assert blend_warnings(T, [_src(0.0, 1.0)], []) == []


def test_pass_years() -> None:
    class P:
        def __init__(self, mjd: float) -> None:
            self.mjd = mjd

    assert pass_years([[P(51544.5), P(51544.5)], []]) == [2000.0]


def test_blend_blocks_typing_unless_the_target_is_clearly_brighter() -> None:
    near = _src(0.0, 3.6, g=16.3)
    # WISE 0855: not in Gaia, so fainter than the G = 16.3 neighbour there: blocked.
    assert blend_blocks_typing(T, [near], YEARS)
    me = {"id": "t", "ra": 100.0, "dec": 10.0, "epoch": 2016.0, "pmra_masyr": 2000.0,
          "pmdec_masyr": 0.0}
    assert blend_blocks_typing(T, [near, {**me, "g_mag": 15.8}], YEARS)  # only 0.5 mag
    assert not blend_blocks_typing(T, [near, {**me, "g_mag": 14.0}], YEARS)
    assert not blend_blocks_typing(T, [_src(0.0, 9.0)], YEARS)  # nothing within a pixel
