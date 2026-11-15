"""`fieldmovers` on the recorded sources of the real W2 visits of the WISE 0855-0714 field
(tests/fixtures/astro/wise-0855-0714-w2-sources.json, written by
`probes/astro/field_movers.py fixture`: every source of S/N 3.5 or more in each of the 23
visits, 2010-2024). The search is not told where the target is. Offline."""

import json
from pathlib import Path

import numpy as np

from pxs.fieldmovers import block, detect, label, link

FIX = Path(__file__).parent / "fixtures" / "astro" / "wise-0855-0714-w2-sources.json"


def _epochs() -> detect.Epochs:
    z = json.loads(FIX.read_text())
    rows = [np.array(r, float).reshape(-1, 4) for r in z["sources"]]
    rows = [r[r[:, 2] >= detect.SNR_MIN] for r in rows]
    return detect.Epochs(band=z["band"], ids=tuple(z["ids"]), years=np.array(z["years"]),
                         xy=tuple(r[:, :2] for r in rows), snr=tuple(r[:, 2] for r in rows),
                         err_px=tuple(r[:, 3] for r in rows),
                         pixscale_arcsec=z["pixscale_arcsec"], size_px=z["size_px"])


def test_wise_0855_is_the_only_mover_and_its_motion_is_the_published_one() -> None:
    ep = _epochs()
    band = block.Band(ep, tuple(link.tracks(ep)))
    found, conflicts = block.movers([band])
    assert len(found) == 1 and conflicts == 0 and len(band.tracks) >= 12
    tr = found[0].track
    pmra, pmdec, err = label.motion_masyr(tr, ep.pixscale_arcsec)
    # Published: (-8123.7, +673.2) mas/yr. Recorded on 15 Nov 2026: (-8131, +664) +- 25.
    assert abs(pmra + 8123.7) < 3 * err < 120 and abs(pmdec - 673.2) < 3 * err
    assert len(tr.epochs) >= 20 and block.coverage(tr, ep) > 0.85
    assert block.shift_arcsec(tr, ep) > 100  # 8"/yr for 14 years


def test_the_static_sources_of_the_field_do_not_move() -> None:
    ep = _epochs()
    band = block.Band(ep, tuple(link.tracks(ep)))
    still = [t for t in band.tracks if len(t.epochs) == len(ep.years)]
    assert len(still) >= 8
    assert all(block.shift_arcsec(t, ep) < 1.0 for t in still)
    assert np.median([t.chi2 for t in still]) < 2.0  # the per-visit errors are about right


def test_shuffled_dates_do_not_bring_the_fast_mover_back() -> None:
    # A faint static source whose position jumps between visits passes in 1 of these 5
    # shuffles (this is W2 alone; the full search also checks W1). WISE 0855 never does.
    ep = _epochs()
    slow = []
    for seed in range(5):
        fake = detect.scrambled(ep, np.random.default_rng(seed))
        found = block.movers([block.Band(fake, tuple(link.tracks(fake)))])[0]
        slow += [abs(label.motion_masyr(m.track, ep.pixscale_arcsec)[0]) < 1000 for m in found]
    assert all(slow) and len(slow) <= 1
