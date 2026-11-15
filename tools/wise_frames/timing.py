"""Does a position have 2010 three-band frames? Decided from its other visits' dates.

Only IRSA's TAP lists the three-band phase (SIA's collection is empty), so with TAP down the
phase is decided by timing. WISE sees a position when the Sun is about 90 degrees from it,
so visits recur at the same time of year; NEOWISE's twenty-odd visits, moved back by whole
years, predict the 2010 visits. A position whose predicted 2010 visits all miss the
three-band window (with a margin for the few days of drift seen between NEOWISE years and
2010) has no frames in that phase. The prediction is checked against the 2010 visits SIA
did list.
"""

from __future__ import annotations

from collections.abc import Sequence

YEAR_D = 365.25
# 3-band cryogenic phase: 2010 Aug 6 to Sep 29 (WISE Explanatory Supplement).
THREEBAND_MJD = (55414.0, 55468.0)
YEAR_2010_MJD = (55210.0, 55593.0)  # survey start 2010 Jan 14 to end of post-cryo 2011 Feb 1
MARGIN_D = 7.0  # the 2010 vs NEOWISE drift seen at the gallery targets is up to about 4 d

Interval = tuple[float, float]


def predicted_2010(visits: Sequence[Interval]) -> list[Interval]:
    """NEOWISE visit intervals (MJD) moved back by whole years into 2010, merged."""
    out: list[Interval] = []
    for start, end in visits:
        n = round((start - (YEAR_2010_MJD[0] + YEAR_2010_MJD[1]) / 2) / YEAR_D)
        for k in (n - 1, n, n + 1):
            s, e = start - k * YEAR_D, end - k * YEAR_D
            if e >= YEAR_2010_MJD[0] and s <= YEAR_2010_MJD[1]:
                out.append((s, e))
    out.sort()
    merged: list[Interval] = []
    for s, e in out:
        if merged and s <= merged[-1][1] + 2 * MARGIN_D:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def overlaps(a: Interval, b: Interval, margin: float = 0.0) -> bool:
    return a[0] - margin <= b[1] and b[0] <= a[1] + margin


def threeband_visit(neowise_visits: Sequence[Interval]) -> Interval | None:
    """The predicted 2010 visit that may fall in the three-band window, or None."""
    return next((v for v in predicted_2010(neowise_visits)
                 if overlaps(v, THREEBAND_MJD, MARGIN_D)), None)


def unmatched(neowise_visits: Sequence[Interval], seen_2010: Sequence[Interval]) -> list[Interval]:
    """Predicted 2010 visits outside the three-band window with no listed 2010 visit near
    them: if this is not empty, the prediction is not trusted."""
    return [p for p in predicted_2010(neowise_visits)
            if not overlaps(p, THREEBAND_MJD, MARGIN_D)
            and YEAR_2010_MJD[0] + MARGIN_D <= p[0] and p[1] <= YEAR_2010_MJD[1] - MARGIN_D
            and not any(overlaps(p, s, MARGIN_D) for s in seen_2010)]
