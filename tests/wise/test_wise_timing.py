"""The three-band phase is decided from the dates of a target's NEOWISE visits."""

from wise_frames import timing

# Visit MJDs from IRSA SIA on 14 Nov 2026 (first NEOWISE years; UGPS ends rounded).
UGPS_NEO = [(56945.5, 56946.7), (57117.4, 57118.6), (57312.0, 57313.2), (57476.5, 57477.7)]
UGPS_2010 = [(55293.7, 55294.9), (55485.2, 55486.4)]
BARNARD_NEO = [(56737.0, 56741.0), (56919.1, 56920.4), (57101.6, 57102.8), (57278.1, 57286.9)]
BARNARD_2010 = [(55274.9, 55276.1)]


def test_a_target_seen_outside_the_window_has_no_threeband_frames() -> None:
    assert timing.threeband_visit(UGPS_NEO) is None
    assert timing.unmatched(UGPS_NEO, UGPS_2010) == []


def test_a_target_seen_in_august_2010_has_a_threeband_visit() -> None:
    hit = timing.threeband_visit(BARNARD_NEO)
    assert hit is not None and timing.overlaps(hit, timing.THREEBAND_MJD)
    assert timing.unmatched(BARNARD_NEO, BARNARD_2010) == []


def test_a_prediction_with_no_listed_visit_is_not_trusted() -> None:
    assert timing.unmatched(UGPS_NEO, []) != []
