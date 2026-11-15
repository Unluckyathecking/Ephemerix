"""Does plain bilinear resampling smear flagged SPHEREx pixels over the grid? Plain vs
normalised interpolation (pxs.grid.reproject_to_grid min_good_weight=0.5) on real frames.

    uv run python probes/spherex/smear.py <slug> [window_lo window_hi]

Reports, per frame layer, the share of grid pixels that are NaN, and for the stacked pass
the NaN share and the robust background noise. Uses the stamp cache. Written with Claude Code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

from pxs import build
from pxs.grid import reproject_to_grid
from pxs.render import frame_levels
from pxs.spherex import find_frames_for_target, group_passes, stack
from pxs.target import load_targets

REPO = Path(__file__).resolve().parents[2]


def run(slug: str, window: tuple[float, float]) -> None:
    (t,) = [x for x in load_targets(REPO / "data" / "targets.json") if x.slug == slug]
    grid, _ = build.choose_grid(t, build.GridParams())
    passes = group_passes(find_frames_for_target(t))
    for mode, weight in (("plain", None), ("normalised", 0.5)):
        stack.reproject_to_grid = (lambda d, w, g, mw=weight: reproject_to_grid(d, w, g, mw))
        layer_nan, stack_nan, noise = [], [], []
        for pas in passes:
            st = stack.stack_pass(pas, grid, window, t)
            if st is None:
                continue
            stack_nan.append(np.isnan(st.image).mean())
            noise.append(frame_levels(st.image).noise)
            stamps = [s for _, s in stack.read_many(
                [(f, grid.center_ra, grid.center_dec) for f in pas.frames],
                stack.stamp_half(grid), with_psf=False).stamps]
            sel = stack._select(stamps, [s.mjd for s in stamps], *window, grid, t)
            layer_nan += [np.isnan(stack.frame_layer(s, grid)[0]).mean() for s, _ in sel]
        print(f"{slug} {window} {mode}: per-frame NaN {np.mean(layer_nan):.3f}, stack NaN "
              f"{np.mean(stack_nan):.4f}, background noise {np.round(noise, 5).tolist()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    lo, hi = (float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (4.2, 5.0)
    run(sys.argv[1], (lo, hi))
