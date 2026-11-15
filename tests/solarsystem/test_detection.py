"""The pass detection rule: two bands at S/N >= 5, or one band at S/N >= 50.

Calibrated on offset control tracks.
"""

from __future__ import annotations

import math

from pxs.solarsystem.phot import BandFlux
from pxs.solarsystem.pipeline import DETECTED, MARGINAL, NOT_DETECTED, PassResult, pass_outcome
from pxs.spherex.types import Pass


def test_two_bands_at_five_is_detected() -> None:
    assert pass_outcome([5.0, 5.0, 0.1, -1.0]) == DETECTED
    assert pass_outcome([46.6, 35.7, 21.5, 3.0, 1.1, 0.1]) == DETECTED


def test_one_band_only_is_marginal() -> None:
    # 55636 off_dec: one band at S/N 20 on an empty track position
    assert pass_outcome([20.0, 3.5, -0.3, -1.5]) == MARGINAL
    assert pass_outcome([5.0, 4.99]) == MARGINAL


def test_one_very_strong_band_counts_only_when_no_other_band_was_measured() -> None:
    # Hebe: saturated in five bands, S/N 681 in the sixth
    assert pass_outcome([681.0, math.nan, math.nan]) == DETECTED
    assert pass_outcome([49.9]) == MARGINAL
    # a bright star crossed by the track gives one strong band and quiet measured others
    assert pass_outcome([681.0, 1.0]) == MARGINAL


def test_nothing_at_five_is_not_detected() -> None:
    assert pass_outcome([4.9, 4.9, 4.9]) == NOT_DETECTED
    assert pass_outcome([]) == NOT_DETECTED


def test_non_finite_values_are_ignored() -> None:
    assert pass_outcome([math.nan, 6.0, math.nan, 5.5]) == DETECTED
    assert pass_outcome([math.nan, math.inf, 6.0]) == MARGINAL


def _result(snrs: list[float]) -> PassResult:
    bands = tuple(BandFlux(f"spx-b{i + 1}", 10, s, 1.0) for i, s in enumerate(snrs))
    return PassResult(Pass(()), (), bands, None, bands, (), ())


def test_pass_result_exposes_outcome_detected_and_candidate() -> None:
    marginal = _result([12.0, 1.0, 0.0])
    assert marginal.outcome == MARGINAL and not marginal.detected and marginal.candidate
    real = _result([12.0, 7.0, 0.0])
    assert real.outcome == DETECTED and real.detected and real.candidate
    empty = _result([1.0, 0.0])
    assert empty.outcome == NOT_DETECTED and not empty.detected and not empty.candidate
