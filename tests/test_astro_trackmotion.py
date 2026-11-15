"""`trackmotion`: the manifest's measured_motion from all W2 frames, on synthetic stacks."""

import numpy as np

from pxs import trackmotion
from pxs.astrometry import decimal_year, propagate
from pxs.grid import Grid, Stack
from pxs.target import Target

SIGMA = 7.3 / 2.3548  # W2 PSF on the 1"/px grid
T = Target(name="t", ra=62.76, dec=47.24, epoch=2017.2, pmra_masyr=440.0, pmdec_masyr=-150.0,
           w1_mag=17.0, w2_mag=14.7)
GRID = Grid(center_ra=T.ra, center_dec=T.dec, fov_arcsec=120.0, size_px=120)
MJDS = 51544.5 + (np.linspace(2010.2, 2024.2, 22) - 2000.0) * 365.25


def _stacks(pmra: float, pmdec: float, amp: float = 8.0, band: str = "W2", seed: int = 0):
    """22 visits of a source moving at (pmra, pmdec) mas/yr through `T`'s catalogue place."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:120, 0:120] + 0.5
    out = []
    for mjd in MJDS:
        ra, dec = propagate(T.ra, T.dec, T.epoch, pmra, pmdec, float(decimal_year(mjd)))
        x, y = (float(v) for v in GRID.sky_to_px(ra, dec))
        img = 100.0 + rng.normal(0.0, 1.0, (120, 120))
        img = img + amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA**2))
        out.append((band, Stack(image=img.astype(np.float32), mission="WISE", band=band,
                                wavelength_um=(4.0, 5.2), mjd=float(mjd), date_span_days=1.0,
                                n_exposures=12, native_pixscale_arcsec=2.75)))
    return out


def test_measures_the_motion_that_is_in_the_frames_not_the_catalogue_one() -> None:
    m = trackmotion.measure(T, GRID, _stacks(300.0, -250.0), [])  # catalogue says 440, -150
    assert m is not None and m["method"] == "all_frames"
    assert m["n_frames"] == 22 and m["n_detections"] == 0  # no frame holds a detection
    assert abs(m["pmra_masyr"] - 300.0) < 3 * m["err_pmra_masyr"]
    assert abs(m["pmdec_masyr"] + 250.0) < 3 * m["err_pmdec_masyr"]
    assert abs(m["pmra_masyr"] - 440.0) > 3 * m["err_pmra_masyr"]  # so a mismatch would show
    assert m["parallax_model"] == "none" and 13.9 < m["baseline_years"] < 14.1


def test_nothing_measured_without_w2_frames_or_a_source() -> None:
    assert trackmotion.measure(T, GRID, _stacks(440.0, -150.0, band="W1"), []) is None
    assert trackmotion.measure(T, GRID, _stacks(440.0, -150.0, amp=0.0), []) is None
    assert trackmotion.measure(T, GRID, _stacks(440.0, -150.0)[:5], []) is None


def test_fill_adds_the_motion_and_a_note_only_when_there_is_none() -> None:
    stacks = _stacks(440.0, -150.0)
    empty = {"measured_motion": None, "warnings": ["w"]}
    out = trackmotion.fill(empty, T, GRID, stacks, [])
    assert out["measured_motion"]["method"] == "all_frames"
    assert out["warnings"][0] == "w" and "all 22 W2 images" in out["warnings"][1]
    assert empty == {"measured_motion": None, "warnings": ["w"]}  # input untouched
    have = {"measured_motion": {"pmra_masyr": 1.0}, "warnings": []}
    assert trackmotion.fill(have, T, GRID, stacks, []) is have
    assert trackmotion.fill(empty, T, GRID, stacks, None) is empty  # CatWISE query failed
    assert trackmotion.fill(empty, T, GRID, _stacks(0.0, 0.0, amp=0.0), []) is empty


def _star(w2: float, east_arcsec: float) -> dict:
    """A static CatWISE source `east_arcsec` east of the target's catalogue place."""
    return {"id": "s", "ra": T.ra + east_arcsec / 3600.0 / np.cos(np.radians(T.dec)),
            "dec": T.dec, "epoch": 2015.4, "pmra_masyr": 0.0, "pmdec_masyr": 0.0,
            "w1_mag": w2, "w2_mag": w2}


def test_no_fit_next_to_a_star_four_magnitudes_brighter() -> None:
    # The audit's case: a Gaussian "finds" a source in the wings of a bright star. Here the
    # target is real, and still nothing is reported when the star is that close.
    stacks = _stacks(440.0, -150.0)
    assert trackmotion.measure(T, GRID, stacks, [_star(T.w2_mag - 4.0, 9.0)]) is None
    assert trackmotion.measure(T, GRID, stacks, [_star(T.w2_mag - 4.0, -14.0)]) is None  # 2010
    far = trackmotion.measure(T, GRID, stacks, [_star(T.w2_mag - 4.0, 30.0)])
    fainter = trackmotion.measure(T, GRID, stacks, [_star(T.w2_mag - 3.0, 9.0)])
    assert far is not None and fainter is not None


def test_a_track_off_the_frame_gives_nothing_and_does_not_raise() -> None:
    away = Target(name="away", ra=T.ra + 0.5, dec=T.dec, epoch=T.epoch, pmra_masyr=440.0,
                  pmdec_masyr=-150.0, w2_mag=14.7)
    edge = Target(name="edge", ra=T.ra, dec=T.dec + 55.0 / 3600.0, epoch=T.epoch,
                  pmra_masyr=440.0, pmdec_masyr=-150.0, w2_mag=14.7)
    stacks = _stacks(440.0, -150.0)
    assert trackmotion.measure(away, GRID, stacks, []) is None
    assert trackmotion.measure(edge, GRID, stacks, []) is None
    assert trackmotion.fill({"measured_motion": None, "warnings": []}, away, GRID, stacks,
                            []) == {"measured_motion": None, "warnings": []}
