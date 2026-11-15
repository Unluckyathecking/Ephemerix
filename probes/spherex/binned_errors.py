"""How honest are binned SPHEREx errors? Compare the nominal inverse-variance error of each
wavelength bin with the real scatter of the same binned mean at 8 empty positions.

    uv run python probes/spherex/binned_errors.py eps-ind-b wise-0855

Reads stamps from the stamp cache (run a build first). For every frame, the forced flux is
measured at the target and at the 8 empty offsets 8 px away (photometry.OFFSETS), with the
per-detector error scale already applied, exactly as extract_spectrum does. Each bin of
spectra.bin_edges then gets the inverse-variance mean of the target points and, with the
same weights, of the empty points at each offset. Reported per detector:
  - empty/nominal: robust sigma (1.4826 MAD) of (binned empty flux / nominal binned error),
    pooled over bins and offsets. 1.0 means the nominal error is honest.
  - sqrt(chi2_red): median over bins of the within-bin reduced chi-square of target points.
Written with Claude Code.
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from pxs.spectra import bin_edges
from pxs.spherex import find_frames_for_target, group_passes
from pxs.spherex.photometry import OFFSETS, measure
from pxs.spherex.spectrum import detector_scales
from pxs.spherex.stamps import position_at, read_many
from pxs.target import load_targets

REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("binned_errors")


def frame_rows(target) -> list[tuple]:
    """(wl, detector, flux, err, empty fluxes[8]) per usable frame over all passes."""
    rows = []
    for pas in group_passes(find_frames_for_target(target)):
        jobs = [(f, *position_at(target, f.mjd)) for f in pas.frames]
        stamps = [s for _, s in read_many(jobs).stamps]
        if not stamps:
            continue
        scales = detector_scales(stamps)
        for s in stamps:
            m = measure(s)
            if not m.ok:
                continue
            k = scales[s.detector]
            empty = [measure(s, dx, dy) for dx, dy in OFFSETS]
            ef = [e.flux_mjy if e.ok else np.nan for e in empty]
            rows.append((s.wave_um, s.detector, m.flux_mjy, m.err_mjy * k, ef))
    return rows


def per_bin(rows):
    wl = np.array([r[0] for r in rows])
    edges = bin_edges(wl.min(), wl.max())
    idx = np.searchsorted(edges, wl, side="right") - 1
    out = []
    for b in sorted(set(idx.tolist())):
        sel = [r for r, i in zip(rows, idx) if i == b]
        w = np.array([1 / r[3] ** 2 for r in sel])
        f = np.array([r[2] for r in sel])
        sig = 1 / np.sqrt(w.sum())
        mean = (w * f).sum() / w.sum()
        e = np.array([r[4] for r in sel])  # n x 8
        ok = np.isfinite(e)
        emean = np.array([(w[ok[:, k]] * e[ok[:, k], k]).sum() / w[ok[:, k]].sum()
                          if ok[:, k].any() else np.nan for k in range(e.shape[1])])
        chi = ((f - mean) ** 2 * w).sum() / (len(sel) - 1) if len(sel) > 1 else np.nan
        det = max(set(r[1] for r in sel), key=[r[1] for r in sel].count)
        out.append((edges[b], det, len(sel), mean, sig, emean / sig, chi))
    return out


def report(slug: str) -> None:
    (t,) = [x for x in load_targets(REPO / "data" / "targets.json") if x.slug == slug]
    bins = per_bin(frame_rows(t))
    by_det = defaultdict(list)
    for b in bins:
        by_det[b[1]].append(b)
    print(f"\n{slug}: {len(bins)} bins, median points per bin "
          f"{np.median([b[2] for b in bins]):.0f}")
    print("det  bins  empty/nominal  median sqrt(chi2_red)  median S/N nominal")
    pooled = []
    for d in sorted(by_det):
        z = np.concatenate([b[5] for b in by_det[d]])
        z = z[np.isfinite(z)]
        pooled.append(z)
        rs = 1.4826 * np.median(np.abs(z - np.median(z)))
        chi = np.nanmedian([np.sqrt(b[6]) for b in by_det[d]])
        snr = np.median([b[3] / b[4] for b in by_det[d]])
        print(f"D{d}   {len(by_det[d]):4d}   {rs:6.2f}         {chi:6.2f}               {snr:7.1f}")
    z = np.concatenate(pooled)
    print(f"all  {len(bins):4d}   {1.4826 * np.median(np.abs(z - np.median(z))):6.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    for slug in sys.argv[1:]:
        report(slug)
