"""Compare frame sets from the local index and live IRSA SIA2 for gallery targets.

    python tools/spherex_index/verify_vs_sia.py INDEX_DIR slug [slug ...]

Uses the same search circle as `find_frames_for_target`. Costs one SIA query per target and
collection (cached on disk by the pipeline for a day). Prints a markdown table and lists
every frame present in only one of the two sets.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import replace
from pathlib import Path

from pxs.spherex import config, localindex
from pxs.spherex.localindex import FrameIndex
from pxs.spherex.query import find_frames, search_circle
from pxs.target import load_targets

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("index", type=Path)
    ap.add_argument("slugs", nargs="+")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    os.environ.pop(localindex.ENV_DIR, None)  # find_frames must really ask SIA here
    t0 = time.perf_counter()
    idx = FrameIndex.load(a.index)
    print(f"index loaded: {len(idx)} frames in {time.perf_counter() - t0:.1f} s\n")
    targets = {t.slug: t for t in load_targets(REPO / "data" / "targets.json")}
    print("| target | radius deg | SIA frames | index frames | only SIA | only index "
          "| SIA s | index ms |\n|---|---|---|---|---|---|---|---|")
    notes: list[str] = []
    for slug in a.slugs:
        ra, dec, radius = search_circle(targets[slug])
        t = time.perf_counter()
        sia = find_frames(ra, dec, radius)
        t_sia = time.perf_counter() - t
        t = time.perf_counter()
        loc = idx.find([(ra, dec)], radius, config.COLLECTIONS)
        t_loc = time.perf_counter() - t
        s_sia, s_loc = {f.s3_key: f for f in sia}, {f.s3_key: f for f in loc}
        only_sia, only_loc = sorted(s_sia.keys() - s_loc.keys()), sorted(s_loc.keys() - s_sia.keys())
        field_diffs = [k for k in s_sia.keys() & s_loc.keys()
                       if replace(s_sia[k], mjd=0.0) != replace(s_loc[k], mjd=0.0)
                       or abs(s_sia[k].mjd - s_loc[k].mjd) > 2e-6]
        print(f"| {slug} | {radius:.5f} | {len(sia)} | {len(loc)} | {len(only_sia)} "
              f"| {len(only_loc)} | {t_sia:.2f} | {t_loc * 1e3:.1f} |")
        notes += [f"{slug}: only in SIA: {k} (mjd {s_sia[k].mjd})" for k in only_sia]
        notes += [f"{slug}: only in index: {k} (mjd {s_loc[k].mjd})" for k in only_loc]
        notes += [f"{slug}: field mismatch {k}: {s_sia[k]} vs {s_loc[k]}" for k in field_diffs]
    print("\n" + ("\n".join(notes) if notes else "no differences"))


if __name__ == "__main__":
    main()
