"""Secondary-band centroids must agree with the same epoch's reference band."""

from pxs.crossband import check


def _f(band: str, mission: str, mjd: float, centroid, pred=(100.0, 100.0), err=0.14) -> dict:
    return {"id": f"{band}-{mjd}", "band": band, "mission": mission, "mjd": mjd,
            "predicted_px": list(pred), "centroid_px": None if centroid is None else
            list(centroid), "centroid_err_arcsec": None if centroid is None else err,
            "warnings": []}


def test_w1_on_a_static_neighbour_is_dropped() -> None:
    # WISE 0855, 2010: W2 on the prediction, W1 2.9" away on a static source (1"/px grid).
    frames = [_f("W2", "WISE", 55330.0, (100.3, 100.2), err=0.28),
              _f("W1", "WISE", 55330.0, (102.9, 100.8), err=0.28)]
    w2, w1 = check(frames, 1.0)
    assert w2 == frames[0]
    assert w1["centroid_px"] is None and w1["centroid_err_arcsec"] is None
    assert "disagrees with W2" in w1["warnings"][0]
    assert frames[1]["centroid_px"] is not None  # input untouched


def test_agreeing_bands_and_frames_without_reference_are_kept() -> None:
    frames = [_f("W2", "WISE", 55330.0, (100.3, 100.2)),
              _f("W1", "WISE", 55330.5, (100.5, 100.1)),
              _f("W1", "WISE", 56000.0, (104.0, 100.0)),  # no W2 at this visit
              _f("spx-b6", "SPHEREx", 61000.0, None),
              _f("spx-b2", "SPHEREx", 61010.0, (105.0, 100.0), err=0.31)]
    assert check(frames, 1.0) == frames


def test_spherex_band_checked_against_spx_b6_of_the_pass() -> None:
    frames = [_f("spx-b6", "SPHEREx", 61000.0, (100.2, 100.1), err=0.31),
              _f("spx-b2", "SPHEREx", 61010.0, (106.5, 96.4), pred=(100.5, 100.0), err=0.31)]
    assert check(frames, 1.0)[1]["centroid_px"] is None
