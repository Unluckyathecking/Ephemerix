"""Replay the type gate on all 17 published views (web/gallery) and pin every type row.

No download and no build: each manifest stores its spectrum points, its Gaia and CatWISE
lists and its frame detections, which is everything the gate reads. A change to the matcher
or the gate that alters a verdict, a best type, a range, a provisional mark or the sentence a
visitor reads fails here and has to be written into EXPECTED on purpose.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from pxs import blend, catalogs
from pxs.astrometry import decimal_year
from pxs.spectra import chosen_match
from pxs.target import load_targets
from pxs.typegate import BLEND_REASON, FAINT_NOTE, UNSEEN_REASON, neighbours_checked, vet
from pxs.validation.rules import type_check
from pxs.validation.stats import declined_reason

REPO = Path(__file__).resolve().parents[1]
GALLERY = REPO / "web" / "gallery"
TARGETS = {t.slug: t for t in load_targets(REPO / "data" / "targets.json")}
MJD_ZERO = np.datetime64("1858-11-17T00:00:00")
SATURATED = ("Every SPHEREx spectrum point is unusable ({} where the target saturates the "
             "detector, {} where too much of the target is covered by bad pixels), so there is "
             "no spectrum to judge.")
CONTAMINATED = ("The spectrum is not classified because a brighter catalogued source ({}) {} "
                "arcsec away falls inside the area the SPHEREx photometry is fitted over; its "
                "light there is estimated at {} times the target's own, or more.")
NEIGHBOUR = ("A catalogued source ({}) {} arcsec away may contribute about {} of the light at "
             "these wavelengths, or more; treat the type as provisional.")
TOO_FEW = ("The spectrum is not classified because only 5 of its points between 1.0 and 5.0 µm "
           "are usable, and at least 8 are needed to compare it with the templates.")
COUNT = ("SPHEREx detects the object at only {} wavelengths ({} µm), which is too little of the "
         "spectrum to classify it.")

# slug: (verdict, best, range, kind of provisional, the sentence shown)
EXPECTED = {
    "barnards-star": ("not_applicable", None, None, None, SATURATED.format(357, 2)),
    "epsilon-indi-b": ("pass", "T2", ["T1", "T3"], None, None),
    "wise-0855-0714": ("refused", None, None, None, BLEND_REASON),
    "rw-aurigae": ("refused", None, None, None, TOO_FEW),
    "r-draconis": ("not_applicable", None, None, None, SATURATED.format(538, 1)),
    "wisea-1101-5400": ("pass", "T6", ["T5", "T7"], None, None),
    "cwise-0623-0715": ("refused", None, None, None, CONTAMINATED.format("W1 14.4", "7.3", 2)),
    "cwise-2112-0529": ("pass", "T1", ["T0", "T2"], "neighbour",
                        NEIGHBOUR.format("W2 16.7", "4.9", "15%")),
    "cwise-2021-1524": ("refused", None, None, None, UNSEEN_REASON),
    "cwise-0411-4714": ("refused", None, None, None, UNSEEN_REASON),
    "cwise-2029-7910": ("pass", "L1", ["L0", "L2"], None, None),
    "cwise-1055-5443": ("pass", "Y0", ["T8", "Y1"], "faint", FAINT_NOTE),
    "denis-0255-4700": ("pass", "L9", ["L8", "T0"], None, None),
    "2mass-0559-1404": ("pass", "T4", ["T3", "T5"], None, None),
    "2mass-0415-0935": ("pass", "T8", ["T7", "T9"], None, None),
    "ugps-0722-0540": ("pass", "T9", ["T8", "Y0"], "neighbour",
                       NEIGHBOUR.format("W1 16.3", "4.0", "22%")),
    "wise-1541-2250": ("refused", None, None, None, CONTAMINATED.format("W1 16.6", "2.0", 2)),
}


def _year(spec: dict) -> float:
    days = [(np.datetime64(spec[k].rstrip("Z")) - MJD_ZERO) / np.timedelta64(1, "D")
            for k in ("date_start", "date_end")]
    return float(decimal_year(float(np.mean(days))))


def replay(slug: str) -> tuple[dict, list[str]]:
    """(the scoreboard's type row, the gate's sentences) for a published view, as the build
    would produce them from the stored spectra, catalogue lists and detections."""
    target = TARGETS[slug]
    m = json.loads((GALLERY / slug / "manifest.json").read_text())
    spectra = m["spectra"]
    gaia = m["overlays"].get("gaia", [])
    catwise = None if catalogs.catwise_failed(m["warnings"]) else m["overlays"].get("catwise", [])
    years = [_year(s) for s in spectra if s["id"] != "spx-all"]
    refuse, caution = blend.contamination_gate(target, catwise, years)
    match, notes = vet(chosen_match(spectra), spectra,
                       blend.blend_blocks_typing(target, gaia, years), refuse,
                       seen=any(f.get("centroid_px") for f in m["frames"]), caution=caution,
                       checked=neighbours_checked(target, catwise,
                                                  catalogs.gaia_failed(m["warnings"])))
    reason = declined_reason({"warnings": notes}) or declined_reason(m)
    return type_check(match, target.known_type, bool(spectra), None if match else reason), notes


def test_every_gallery_target_is_pinned() -> None:
    assert set(EXPECTED) == set(TARGETS) and len(EXPECTED) == 17


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_published_view_replays_to_the_pinned_type_row(slug: str) -> None:
    verdict, best, rng, kind, sentence = EXPECTED[slug]
    row, _ = replay(slug)
    assert (row["verdict"], row["best"], row["range"]) == (verdict, best, rng)
    assert row["provisional_kind"] == kind and bool(row["provisional"]) == (kind is not None)
    assert (row["provisional"] if kind else row["reason"]) == sentence


def test_the_stronger_reason_is_the_one_shown_and_the_count_sentence_follows() -> None:
    _, notes = replay("cwise-0623-0715")
    assert notes == [EXPECTED["cwise-0623-0715"][4], COUNT.format(12, "1.7 to 4.2")]
    _, notes = replay("cwise-0411-4714")
    assert notes == [UNSEEN_REASON, COUNT.format(10, "3.8 to 4.4")]


def test_the_only_faint_type_is_open_ended_and_seen_in_an_image() -> None:
    row, _ = replay("cwise-1055-5443")
    assert row["range_open_cold"] and not row["range_open_warm"]
    faint = [s for s in EXPECTED if EXPECTED[s][3] == "faint"]
    assert faint == ["cwise-1055-5443"]
