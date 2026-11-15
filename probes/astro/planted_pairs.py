"""Planted pairs in real WISE frames, measured through the same steps as centroid.detect.

    uv run python probes/astro/planted_pairs.py W2 cwise-1055-5443 wise-1541-2250 cwise-2112-0529

A real isolated star (S/N 7-40) is measured alone: the truth. A copy of the frame shifted by
a whole number of pixels and scaled by q is added, which puts a copy of the star at that
offset: a neighbour with the real PSF and real noise. The candidate is then the peak of the
blended frame nearest the star (as detect() takes the peak nearest the prediction), measured
with the single fit and with the joint fit; the joint fit is told the neighbour's place as a
catalogued one when q is within what `fitblend.neighbours_px` would pass. Output per
separation and q: median shift towards the neighbour (arcsec, 1"/px) of both fits, how often
the joint fit was used, and the robust rms of shift / stated error.

Numbers quoted in src/pxs/pairfit.py come from this. Needs cache/astro/<slug>.pkl
(dump_stacks.py). Written with Claude Code.
"""

from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
from stacks import load, robust_rms

from pxs import centroid, pairfit

SEPS = (8, 9, 10, 12, 14, 16)
QS = (0.3, 0.6, 1.0, 1.5, 2.0)
VISITS = (1, 5, 9, 13, 17, 21)


def isolated(fr, lo=7.0, hi=40.0, gap=24.0, edge=36.0):
    ny, nx = fr.snr.shape
    pk = centroid._peaks(fr, (nx / 2, ny / 2), nx, 4.0)
    return [p for p in pk if lo <= p[2] <= hi and edge < p[0] < nx - edge
            and edge < p[1] < ny - edge
            and all(q is p or np.hypot(q[0] - p[0], q[1] - p[1]) >= gap for q in pk)]


def one_case(fr, st, star, truth, dx, dy, q, pixscale):
    """(single-fit shift, joint-fit shift or None, joint-fit pull or None), or None."""
    img = fr.resid + q * np.roll(fr.resid, (dy, dx), axis=(0, 1))
    fr2 = replace(fr, resid=img, snr=centroid._snr_map(img, fr.usable, fr.sigma_px))
    peaks = centroid._peaks(fr2, star, 15.0, centroid.SNR_MIN)
    if not peaks:
        return None
    u = np.array([dx, dy]) / np.hypot(dx, dy)
    known = [(star[0] + dx, star[1] + dy)] if q <= pairfit.MAX_FLUX_RATIO else []
    one = centroid._fit(fr2, peaks[0])
    m = centroid._measure_peak(fr2, peaks[0], st, pixscale, known)
    joint = m is not None and bool(m[4])
    b1 = None if one is None else float(np.dot([one[0] - truth[0], one[1] - truth[1]], u))
    b2 = float(np.dot([m[0] - truth[0], m[1] - truth[1]], u)) if joint else None
    return b1, b2, (b2 / np.hypot(m[2], truth[2]) if joint else None)


def run(slug: str, band: str) -> list[tuple]:
    d, _, _ = load(slug)
    pix = d["grid"].pixscale_arcsec
    stacks = [st for b, st in d["stacks"] if b == band]
    rows = []
    for st in (stacks[k] for k in VISITS if k < len(stacks)):
        fr = centroid._prepare(st, pix)
        for s in isolated(fr):
            t = centroid._measure_peak(fr, s, st, pix)
            if t is None or t[4]:
                continue
            for sep in SEPS:
                for dx, dy in ((sep, 0), (0, sep), (-sep, 0), (0, -sep)):
                    rows += [(sep, q, *r) for q in QS
                             if (r := one_case(fr, st, s, t, dx, dy, q, pix)) is not None]
    return rows


def main(argv: list[str]) -> int:
    rows = [r for slug in argv[1:] for r in run(slug, argv[0])]
    print(f"{argv[0]}: {len(rows)} cases\nsep    q  cases | single: median | joint: used, median, "
          "robust rms, robust rms of shift/error")
    for sep in SEPS:
        for q in QS:
            sel = [r for r in rows if r[0] == sep and r[1] == q]
            a = [r[2] for r in sel if r[2] is not None]
            b = [r[3] for r in sel if r[3] is not None]
            p = [r[4] for r in sel if r[4] is not None]
            joint = (f"{len(b):3d} {np.median(b):+.3f} {robust_rms(b):.2f} {robust_rms(p):.2f}"
                     if b else "  0")
            print(f"{sep:3d} {q:4.1f} {len(sel):5d} | {np.median(a):+.2f} | {joint}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
