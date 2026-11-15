"""Per-pass measurement helpers of the body-recovery campaign (offline)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from solarsystem_validation.measure import (
    centroid_offset,
    classify_error,
    offset_visits,
    plain,
    shift,
)

from pxs.solarsystem.horizons import EphemPoint
from pxs.solarsystem.track import Visit
from pxs.spherex.types import Frame


def _eph(ra: float, dec: float) -> EphemPoint:
    return EphemPoint(60900.0, ra, dec, 1.0, 2.0, 17.3, 50.0, 49.5, 95.0, 1.1)


def test_shift_east_uses_cos_dec_and_north_is_plain():
    e = shift(_eph(10.0, 60.0), 180.0, 0.0)
    assert e.ra == pytest.approx(10.0 + 180.0 / 3600.0 / 0.5)
    assert e.dec == 60.0 and e.vmag == 17.3 and e.mjd == 60900.0
    n = shift(_eph(359.99, -5.0), 0.0, -180.0)
    assert n.dec == pytest.approx(-5.05) and n.ra == 359.99


def test_shift_wraps_ra():
    assert shift(_eph(359.99, 0.0), 180.0, 0.0).ra == pytest.approx(0.04)


def test_offset_visits_keep_frames_and_shift_positions():
    f = Frame("spherex_dr1", "o", 1, 60900.0, "k", 0.75, 1.1)
    out = offset_visits([Visit(f, _eph(10.0, 0.0))], 0.0, 36.0)
    assert out[0].frame is f and out[0].eph.dec == pytest.approx(0.01)


def _gauss(x0: float, y0: float, size: int = 90, sigma: float = 2.0) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size] + 0.5  # pixel centres, edge convention
    img = 5.0 + 100.0 * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * sigma**2))
    return img.astype(np.float32)


def test_centroid_of_centred_source_is_zero():
    east, north = centroid_offset(_gauss(45.0, 45.0))
    assert abs(east) < 0.1 and abs(north) < 0.1


def test_centroid_signs_follow_the_grid_orientation():
    # +x is west and +y is south on a Grid (both cdelt negative): 2 px = 4 arcsec each.
    east, north = centroid_offset(_gauss(47.0, 43.0))
    assert east == pytest.approx(-4.0, abs=0.3) and north == pytest.approx(4.0, abs=0.3)


def test_centroid_ignores_nans_and_returns_none_without_signal():
    img = _gauss(45.0, 45.0)
    img[0:10, :] = np.nan
    assert centroid_offset(img) is not None
    assert centroid_offset(np.full((90, 90), np.nan, np.float32)) is None
    assert centroid_offset(np.full((90, 90), 3.0, np.float32)) is None


def test_plain_turns_numpy_and_nan_into_json():
    out = plain({"a": np.float32(1.5), "b": [np.int64(2), math.nan], "c": (np.bool_(True),),
                 "d": float("inf")})
    assert out == {"a": 1.5, "b": [2, None], "c": [True], "d": None}
    json.dumps(out, allow_nan=False)


def test_classify_error_by_type():
    from pxs.solarsystem.horizons import HorizonsError
    from pxs.spherex.net import TransientError

    assert classify_error(HorizonsError("x")) == "horizons"
    assert classify_error(TransientError("x")) == "network"
    assert classify_error(TimeoutError("x")) == "timeout"
    assert classify_error(ValueError("x")) == "bug"
