"""What else moved in this patch of sky between 2010 and 2024: the manifest's `field_movers`.

Method. Every source of every WISE visit is found on the common grid (`detect`), the
sources of all visits are linked into tracks (`link`), each track gets a straight-line
motion with an error, the tracks that moved are checked between W2 and W1 and against the
catalogues (`block`, `label`), and the same search is repeated with the visit dates
shuffled to count what it finds when nothing can have moved in a straight line.

Why tracks and not an early-minus-late difference image: a difference shows a mover only
once it has moved about a PSF width (7") and leaves a residual at every bright star whose
PSF differs between the 2010 and later visits; the track of a source seen in every visit
measures its position to 0.03-0.3" per visit, so motions of 0.1"/yr are measured, every
linked source is its own null, and the result is a motion with an error that a catalogue
can be compared with. The price: a mover must be seen in single visits, and one that only
shows in a stack of all visits is not found.

A track is a mover when (`block.moved`) its motion is SIG_MIN times its error, it shifted
MIN_SHIFT_ARCSEC over the baseline, it was seen in COVER_MIN of the visits in which it was
inside the image, and it is not in the wings of a source 40 times brighter; a mover that
the other band also tracks must move the same way there.

Where the limits come from (probes/astro/field_movers.py, the 17 gallery fields, 15 Nov
2026; none was set by which gallery targets pass):

- SIG_MIN 6, MIN_SHIFT_ARCSEC 1, COVER_MIN 0.7: the `null` table. With the dates shuffled
  (40 shuffles of each field) these let 5 "movers" through in 680 searches, 0.007 a field;
  without the coverage limit it is 291 (pieces of the real fast movers, which a shuffle
  cuts into short runs), and with a shift of 0.5" it is 259. In the true order, of 446 tracks
  at Gaia stars slower than 20 mas/yr none passes; without the shift limit 16 pass (bright
  stars with errors of a few mas/yr, where a real 5-20 mas/yr or a small drift is enough).
- detect.SNR_MIN 4: the `planted` table. Sources planted at S/N 5 per visit are recovered
  37-56% of the time with sources kept from S/N 4 and 2-15% from S/N 5 (they drop under the
  limit in too many visits to reach COVER_MIN); the shuffled null is no larger (5 against 8
  in 680). Tried after the first gallery run, which it does not change (11 of 17 targets
  found blind at either value).
- link: V_MAX 12"/yr is above Barnard's Star; the gate, six visits and three years were set
  before any run and not changed.
- label: 3" and "within 3 sigma or 30%" were set before any run and not changed.
- detect.ERR_K and FLOOR_ARCSEC: the scatter of static tracks (its docstring). Against Gaia,
  (measured - Gaia) / error has rms 1.1 in W2 (195 tracks) and 1.2 in W1 (298).

What it finds (`planted`: real PSF, W2 only, 8 fields, 160 per cell, about +-4%): at 0.2 to
8"/yr, 37-56% at S/N 5 per visit (about W2 14.7), 65-76% at S/N 6, 63-77% at S/N 8 and 74-90%
at S/N 12 and up; the rest are lost to blends with field sources. Nothing slower than 1" in
14 years by construction; at 0.1"/yr 14% at S/N 8, 74% at S/N 12, 90% at S/N 25. 1.9% of
planted movers are found with a motion off by more than 3 sigma and 30% (blended on part of
the path), and 19 movers that were neither planted nor the field's own turned up in 1120
planted searches (the 4 looked at lie within 4" of a planted path: the planted mover pulled
off its place by a blend, or a static source it passed over).

What it is not: proof that an unexplained candidate is real. The gallery fields hold none, so
candidates are counted but not listed (`block.SHIP_CANDIDATES`).

`search` never raises: any failure gives a "not_searched" block with the reason.
Written with Claude Code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pxs.fieldmovers import block
from pxs.grid import Grid, Stack
from pxs.target import Target

log = logging.getLogger(__name__)

NO_VISITS = (f"there are fewer than {block.MIN_DETECTIONS} WISE visits of it in any one "
             "band")
NO_CATALOGUES = ("the Gaia and CatWISE lists could not be fetched, so a mover could not be "
                 "told from a known star")
FAILED = "the search failed on these images"


def search(target: Target, grid: Grid, stacks: Sequence[tuple[str, Stack]], ids: Sequence[str],
           gaia: Sequence[dict] | None, catwise: Sequence[dict] | None) -> dict:
    """The `field_movers` block. `ids` are the frame ids of `stacks`; `gaia` and `catwise`
    are the overlay lists, None when their query failed."""
    if gaia is None or catwise is None:
        return block.not_searched(NO_CATALOGUES)
    try:
        bands = [b for name in block.BANDS
                 if (b := block.band_of(stacks, ids, grid, name)) is not None]
        if not bands:
            return block.not_searched(NO_VISITS)
        return block.assemble(bands, target, grid, gaia, catwise)
    except Exception:
        log.exception("field mover search failed")
        return block.not_searched(FAILED)
