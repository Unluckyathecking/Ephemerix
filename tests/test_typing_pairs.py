"""Unresolved-pair test: true positives and false-alarm guards (fixed seeds)."""

import numpy as np
import pytest

from pxs.typing import _clean, load_templates, match_spectrum
from pxs.typing.core import analyse
from pxs.typing.pairs import best_pair
from test_typing_rules import WL, observe, tpl


def blend(primary, secondary, share_at_22):
    def f(wl):
        a, b = tpl(primary), tpl(secondary)
        ra, rb = a(np.array([2.2]))[0], b(np.array([2.2]))[0]
        return (1 - share_at_22) * a(wl) / ra + share_at_22 * b(wl) / rb
    return f


@pytest.mark.parametrize("seed", range(3))
def test_t1_plus_t6_is_reported(seed):
    r = match_spectrum(*observe(blend("T1", "T6", 0.3), 30, seed))
    assert r["class"] == "brown dwarf"
    assert r["pair"] is not None and r["pair"]["types"] == ["T1", "T6"]
    assert r["pair"]["delta_vs_single"] >= 25
    assert r["verdict"] == ("Fits better as two brown dwarfs blended together (about T1 and T6) "
                            "than as one.")


def test_pair_disabled_by_parameter():
    r = match_spectrum(*observe(blend("T1", "T6", 0.3), 30, 0), pairs=False)
    assert r["pair"] is None and "two brown dwarfs" not in r["verdict"]


@pytest.mark.parametrize("snr", [10, 30, 100])
def test_single_templates_do_not_raise_pairs(snr):
    for label in load_templates():
        for seed in range(2):
            r = match_spectrum(*observe(tpl(label), snr, seed))
            assert r["pair"] is None, (label, snr, seed, r["pair"])


def test_sparse_single_templates_do_not_raise_pairs():
    for label in load_templates():
        r = match_spectrum(*observe(tpl(label), 30, 0, wl=WL[::4]))
        assert r["pair"] is None, label


@pytest.mark.parametrize("beta", [-0.3, 0.3])
def test_redder_or_bluer_single_dwarfs_do_not_raise_pairs(beta):
    # A single dwarf whose colour differs from the median template must not look like a pair.
    for label in load_templates():
        def fn(wl, label=label):
            return tpl(label)(wl) * (wl / 2.0) ** beta
        r = match_spectrum(*observe(fn, 30, 0))
        assert r["pair"] is None, (label, beta, r["pair"])


def test_close_types_are_not_reported_even_if_better():
    a = analyse(*_clean(*observe(blend("T4", "T5", 0.5), 100, 0), None))
    assert not best_pair(a).reported


def test_pair_model_curve_reproduces_the_pair_chi2():
    data = observe(blend("T1", "T6", 0.3), 30, 0)
    a = analyse(*_clean(*data, None))
    p = best_pair(a)
    chi2 = float(np.sum(((a.d - p.curve(a.wl)) / a.sigma) ** 2))
    assert chi2 == pytest.approx(p.chi2, rel=1e-6)
    r = match_spectrum(*data)
    assert r["pair"]["model"] == "T1 + T6"
    curve = np.array(r["models"]["T1 + T6"])
    assert curve.shape[1] == 2 and np.all(np.diff(curve[:, 0]) > 0)
    # the stored curve is the same model, sampled on the template grid
    assert np.interp(a.wl, curve[:, 0], curve[:, 1]) == pytest.approx(p.curve(a.wl), rel=0.02)


def test_single_brown_dwarf_has_no_pair_curve():
    r = match_spectrum(*observe(tpl("T8"), 30, 0))
    assert r["pair"] is None and len(r["models"]) == 2
