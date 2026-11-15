"""Survey depths: literature values, derived scalings and the measured per-frame noise."""

from __future__ import annotations

import pytest

from pxs.planetx import depths
from pxs.planetx.photometry import ab_mag


def test_one_map_is_0p75_mag_shallower_and_band_1p54_deeper():
    d = {x.key: x for x in depths.literature_depths()}
    assert d["spx_one_map_channel"].ab["SPHEREx D1"] == pytest.approx((18.75, 19.15), abs=0.005)
    assert d["spx_one_map_channel"].ab["SPHEREx D6"] == pytest.approx((17.05, 18.05), abs=0.005)
    assert d["spx_one_map_band"].ab["SPHEREx D2"][0] == pytest.approx(18.747 + 1.538, abs=0.002)
    assert d["wise"].ab["WISE W1"] == (19.14, 19.40)


def _manifest(errs_mjy, detector=1, flux=0.0, spec_id="spx-2025a"):
    pts = [{"wl_um": 1.0, "flux": flux, "err": e, "detector": detector, "flagged": False}
           for e in errs_mjy]
    return {"spectra": [{"id": spec_id, "unit": "mJy", "points": pts}]}


def test_measured_depth_uses_median_and_quartile_of_faint_points():
    errs = [0.01 * (i + 1) for i in range(20)]  # 10..200 uJy
    m = depths.measured_channel_depth([_manifest(errs)])
    shallow, deep = m.ab["SPHEREx D1"]
    assert shallow == pytest.approx(ab_mag(5 * 105.0), abs=0.01)  # median 105 uJy
    assert deep == pytest.approx(ab_mag(5 * 60.0), abs=0.01)  # 25th percentile: 6th of 20
    assert m.kind == "measured"


def test_measured_depth_skips_bright_points_and_the_all_pass_spectrum():
    bright = _manifest([0.01] * 20, flux=1.0)  # S/N 100
    combined = _manifest([0.01] * 20, spec_id="spx-all")
    assert depths.measured_channel_depth([bright, combined]).ab == {}
