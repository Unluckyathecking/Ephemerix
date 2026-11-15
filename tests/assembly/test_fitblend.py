"""Frames whose centroid fit window holds a catalogued source of similar brightness."""

import numpy as np

from pxs.centroid import JOINT
from pxs.fitblend import BLENDED, flag, is_blended, n_blended, neighbours_px
from pxs.grid import Grid, Stack
from pxs.manifest import motion_frames
from pxs.target import Target

# WISE 1541-2250 (K21 motion) and CatWISE J154151.69-225018.6, W2 14.9, 7" north in 2010.
T = Target(name="t", ra=235.4637315, dec=-22.8406144, epoch=2015.405, pmra_masyr=-902.8,
           pmdec_masyr=-91.4, w1_mag=17.6, w2_mag=14.218)
NEIGHBOUR = {"id": "J154151.69-225018.6", "ra": 235.4653797, "dec": -22.8384719,
             "epoch": 2015.4, "pmra_masyr": -37.49, "pmdec_masyr": 66.08,
             "w1_mag": 14.927, "w2_mag": 14.895}
FRAGMENT = {"id": "J154151.41-225026.1", "ra": 235.4637315, "dec": -22.8406144,
            "epoch": 2015.405, "pmra_masyr": -918.16, "pmdec_masyr": -60.05,
            "w1_mag": 17.8, "w2_mag": 15.1}


def _f(band: str, year: float, mission: str = "WISE", wl=(4.0, 5.2), pix=2.75) -> dict:
    return {"id": f"{band}-{year}", "band": band, "mission": mission, "mjd": 51544.5 + (year - 2000.0) * 365.25,
            "wavelength_um": list(wl), "native_pixscale_arcsec": pix,
            "predicted_px": [100.0, 100.0], "centroid_px": [100.0, 100.0],
            "centroid_err_arcsec": 0.25, "warnings": []}


def test_similar_neighbour_inside_the_fit_window_flags_the_frame() -> None:
    frames = [_f("W2", 2010.2), _f("W2", 2024.1)]
    early, late = flag(frames, T, [NEIGHBOUR, FRAGMENT], pixscale_arcsec=1.0)
    assert is_blended(early) and early["warnings"][0].startswith(BLENDED)
    assert "W2 14.9" in early["warnings"][0]
    assert not is_blended(late)  # 13" away by 2024, outside the 11" window
    assert frames[0]["warnings"] == []  # input untouched
    assert n_blended([early, late]) == 1


def test_target_fragment_and_faint_sources_are_not_neighbours() -> None:
    faint = {**NEIGHBOUR, "w2_mag": 16.5}  # more than 2 mag fainter than the target
    out = flag([_f("W2", 2010.2)], T, [FRAGMENT, faint], pixscale_arcsec=1.0)
    assert not is_blended(out[0])


def test_w1_frames_compare_w1_magnitudes() -> None:
    bright_w1 = {**NEIGHBOUR, "w2_mag": 18.0, "w1_mag": 15.0}  # target W1 is 17.6
    out = flag([_f("W1", 2010.2, wl=(3.0, 3.8))], T, [bright_w1], pixscale_arcsec=1.0)
    assert is_blended(out[0])


def test_no_target_magnitude_means_no_flag() -> None:
    nomag = Target(name="n", ra=T.ra, dec=T.dec, epoch=T.epoch, pmra_masyr=-902.8,
                   pmdec_masyr=-91.4)
    assert not is_blended(flag([_f("W2", 2010.2)], nomag, [NEIGHBOUR], 1.0)[0])


def test_catwise_pieces_of_the_target_along_its_path_are_not_neighbours() -> None:
    # A static piece with W2 14.5 on the target's 2011.9 track (as for Eps Ind B).
    piece = {**FRAGMENT, "id": "piece", "ra": T.ra + 3.5 * 902.8 / 3.6e6 / 0.9216,
             "dec": T.dec + 3.5 * 91.4 / 3.6e6, "pmra_masyr": 0.0, "pmdec_masyr": 0.0,
             "w2_mag": 14.5}
    assert not is_blended(flag([_f("W2", 2013.2)], T, [piece], 1.0)[0])


def test_blended_frames_are_left_out_of_the_motion_fit() -> None:
    frames = flag([_f("W2", 2010.2), _f("W2", 2020.1), _f("W2", 2024.1)], T, [NEIGHBOUR], 1.0)
    assert [f["id"] for f in motion_frames(frames)] == ["W2-2020.1", "W2-2024.1"]


# --- frames fitted together with their neighbour (centroid.JOINT, pairfit) ------------------


def _joint(frame: dict) -> dict:
    return {**frame, "warnings": [f"{JOINT} 7.6 arcsec away"]}


def test_a_frame_fitted_together_with_its_neighbour_is_not_flagged() -> None:
    out = flag([_joint(_f("W2", 2010.2))], T, [NEIGHBOUR], pixscale_arcsec=1.0)
    assert not is_blended(out[0])
    assert len(motion_frames(out)) == 1


def test_a_brighter_neighbour_still_flags_a_jointly_fitted_frame() -> None:
    bright = {**NEIGHBOUR, "w2_mag": T.w2_mag - 0.5}  # 1.6 times the target: not checked
    out = flag([_joint(_f("W2", 2010.2))], T, [bright], pixscale_arcsec=1.0)
    assert is_blended(out[0])


def test_neighbours_px_lists_similar_sources_at_the_frame_epoch() -> None:
    grid = Grid(center_ra=T.ra, center_dec=T.dec, fov_arcsec=240.0, size_px=240)
    st = Stack(image=np.zeros((240, 240), np.float32), mission="WISE", band="W2",
               wavelength_um=(4.0, 5.2), mjd=51544.5 + 10.2 * 365.25, date_span_days=1.0,
               n_exposures=12, native_pixscale_arcsec=2.75)
    bright = {**NEIGHBOUR, "id": "b", "w2_mag": T.w2_mag - 0.5}
    faint = {**NEIGHBOUR, "id": "f", "w2_mag": T.w2_mag + 2.5}
    px = neighbours_px(T, [NEIGHBOUR, FRAGMENT, bright, faint], st, grid)
    assert len(px) == 1  # not the target's own piece, the brighter or the much fainter one
    x, y = grid.sky_to_px(NEIGHBOUR["ra"], NEIGHBOUR["dec"])
    assert abs(px[0][0] - float(x)) < 0.5 and abs(px[0][1] - float(y)) < 0.5
    nomag = Target(name="n", ra=T.ra, dec=T.dec, epoch=T.epoch, pmra_masyr=1.0, pmdec_masyr=1.0)
    assert neighbours_px(nomag, [NEIGHBOUR], st, grid) == []
