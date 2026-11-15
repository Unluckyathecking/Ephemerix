"""The manifest's vetting block."""

import math

import pytest

from pxs.catalogs import CATWISE_EPOCH
from pxs.target import Target
from pxs.vetting import vetting

ROW = {"id": "J041521.26-093500.4", "ra": 63.8386, "dec": -9.5835, "epoch": CATWISE_EPOCH,
       "pmra_masyr": 2200.0, "pmdec_masyr": 500.0, "w1_mag": 15.1, "w2_mag": 12.3}


def _t(**kw) -> Target:
    return Target("x", ROW["ra"], ROW["dec"], CATWISE_EPOCH, **kw)


def test_target_list_magnitudes_and_motion_win() -> None:
    v = vetting(_t(pmra_masyr=2214.2, pmdec_masyr=536.1, w1_mag=15.0, w2_mag=12.26), [ROW])
    mu = math.hypot(2214.2, 536.1) / 1000
    assert v["w1_w2"] == pytest.approx(2.74)
    assert v["reduced_pm_w2"] == pytest.approx(12.26 + 5 * math.log10(mu) + 5, abs=1e-3)
    assert v["catalogue"] == "CatWISE2020 J041521.26-093500.4"


def test_falls_back_to_the_catwise_row() -> None:
    v = vetting(_t(), [ROW])
    assert (v["w1_mag"], v["w2_mag"]) == (15.1, 12.3)
    assert v["reduced_pm_w2"] == pytest.approx(
        12.3 + 5 * math.log10(math.hypot(2200, 500) / 1000) + 5, abs=1e-3)


def test_all_null_without_a_match_or_motion() -> None:
    far = {**ROW, "ra": ROW["ra"] + 0.01}
    assert vetting(_t(), [far]) == {"w1_mag": None, "w2_mag": None, "w1_w2": None,
                                    "reduced_pm_w2": None, "catalogue": None}
    v = vetting(_t(w2_mag=14.0), [])
    assert v["w2_mag"] == 14.0 and v["reduced_pm_w2"] is None
