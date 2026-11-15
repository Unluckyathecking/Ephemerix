"""Light a bright catalogued neighbour adds at the target in the SPHEREx photometry."""

from pxs.blend import contaminant, contamination_reason
from pxs.target import Target

T = Target("Mover", 100.0, 10.0, 2016.0, pmra_masyr=2000.0, pmdec_masyr=0.0, w1_mag=15.2,
           w2_mag=14.7)
YEARS = [2025.5, 2026.3]
COS = 0.984807753  # cos(10 deg)


def _cw(dra_arcsec: float, ddec_arcsec: float, w1: float, w2: float, year: float = 2025.5,
        pm=(0.0, 0.0)) -> dict:
    """CatWISE source (dra, ddec) arcsec from the target at `year`, epoch 2015.4."""
    ra0 = 100.0 + 2000.0 * (year - 2016.0) / 3.6e6 / COS
    ra = ra0 + dra_arcsec / 3600.0 / COS - pm[0] * (year - 2015.4) / 3.6e6 / COS
    return {"id": "n", "ra": ra, "dec": 10.0 + ddec_arcsec / 3600.0, "epoch": 2015.4,
            "pmra_masyr": pm[0], "pmdec_masyr": pm[1], "w1_mag": w1, "w2_mag": w2}


def test_bright_star_two_pixels_away_contaminates() -> None:
    # CWISE J2021+1524: CatWISE J202129.09+152423.4 (W1 9.05) 13.1" away, 280 times brighter.
    hit = contaminant(T, [_cw(13.1, 0.0, 9.05, 9.16)], YEARS)
    assert hit is not None and hit[3] > 1.0  # more light than the target's own
    assert hit[2] < 13.1  # closest approach: the target moves towards it by 2026.3
    reason = contamination_reason(hit)
    assert f"{hit[2]:.1f} arcsec" in reason and "W1 9.1" in reason and "times" in reason


def test_faint_or_distant_sources_do_not() -> None:
    assert contaminant(T, [_cw(13.1, 0.0, 17.5, 17.0)], YEARS) is None  # much fainter
    assert contaminant(T, [_cw(40.0, 0.0, 9.05, 9.16)], YEARS) is None  # far
    assert contaminant(T, [], YEARS) is None


def test_target_pieces_and_no_magnitudes_are_ignored() -> None:
    piece = _cw(0.5, 0.0, 14.0, 13.5, year=2015.4, pm=(2000.0, 0.0))  # moves with the target
    assert contaminant(T, [piece], YEARS) is None
    bare = Target("Bare", 100.0, 10.0, 2016.0, pmra_masyr=2000.0, pmdec_masyr=0.0)
    assert contaminant(bare, [_cw(13.1, 0.0, 9.05, 9.16)], YEARS) is None


def test_two_levels_refuse_above_a_quarter_and_caution_between() -> None:
    from pxs.blend import CONTAM_CAUTION, CONTAM_REFUSE, contamination_gate

    big = _cw(13.1, 0.0, 9.05, 9.16)  # several times the target's light
    refuse, caution = contamination_gate(T, [big], YEARS)
    assert refuse is not None and caution is None
    # W2 16.7 at 4.9" from a W2 14.7 target: about 15% (CWISE 2112-0529).
    mid = _cw(4.9, 0.0, 18.0, 16.71)
    hit = contaminant(T, [mid], YEARS)
    assert hit is not None and CONTAM_CAUTION <= hit[3] < CONTAM_REFUSE
    refuse, caution = contamination_gate(T, [mid], YEARS)
    assert refuse is None and "provisional" in caution and f"{hit[2]:.1f} arcsec" in caution
    assert contamination_gate(T, [_cw(40.0, 0.0, 9.05, 9.16)], YEARS) == (None, None)


def test_no_catwise_means_the_checks_were_not_run() -> None:
    from pxs.blend import CHECKS_NOT_RUN, contamination_gate

    assert contamination_gate(T, None, YEARS) == (None, None)
    assert "could not be run" in CHECKS_NOT_RUN
