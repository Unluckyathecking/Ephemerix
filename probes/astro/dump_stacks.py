"""Stack every WISE visit and SPHEREx pass of a target once and pickle the stacks, so the
centroid and motion fit can be re-run offline in seconds.

    uv run python probes/astro/dump_stacks.py <slug> [...]   ->  cache/astro/<slug>.pkl

Uses the same grid and data modules as `pxs.build`. Written with Claude Code.
"""

from __future__ import annotations

import logging
import pickle
import sys
from pathlib import Path

from pxs import catalogs
from pxs.build import REPO, GridParams, choose_grid, real_source
from pxs.sources import collect_spherex, collect_wise, load_targets, ordered

OUT = REPO / "cache" / "astro"
log = logging.getLogger("dump_stacks")


def dump(slug: str) -> Path:
    target = next(t for t in load_targets(REPO / "data" / "targets.json") if t.slug == slug)
    grid, _ = choose_grid(target, GridParams())
    w = collect_wise(real_source("pxs.wise"), target, grid)
    s = collect_spherex(real_source("pxs.spherex"), target, grid)
    ov, _ = catalogs.overlays(grid)
    out = OUT / f"{slug}.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"target": target, "grid": grid, "stacks": ordered(w.stacks + s.stacks),
               "gaia": ov.get("gaia", []), "warnings": w.warnings + s.warnings}
    out.write_bytes(pickle.dumps(payload))
    log.info("%s: %d stacks -> %s", slug, len(payload["stacks"]), out)
    return out


if __name__ == "__main__":
    import pxs.wise.net

    pxs.wise.net.TIMEOUT_S = (10.0, 120.0)  # offline probe: IRSA visit searches can be slow
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for a in sys.argv[1:]:
        dump(a)
