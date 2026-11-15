"""Print the checkable facts of a built view: per-frame predicted vs measured, warnings, match.

    uv run python probes/assembly/summarise_view.py <view dir>

Written with Claude Code.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def main(view: Path) -> None:
    m = json.loads((view / "manifest.json").read_text())
    print(f"fov {m['fov_arcsec']} size {m['size_px']} center {m['center']}")
    print("id n predicted centroid |d|px err\" flag warnings")
    for f in m["frames"]:
        p, c = f["predicted_px"], f["centroid_px"]
        d = round(math.dist(p, c), 2) if p and c else None
        print(f["id"], f["n_exposures"], p, c, d, f["centroid_err_arcsec"],
              f["flag_fraction"], f["warnings"])
    print("\nwarnings:")
    for w in m["warnings"]:
        print("  -", w)
    for s in m["spectra"]:
        pts = s["points"]
        print(f"spectrum {s['id']} {s['label']}: {len(pts)} points, "
              f"{sum(p['flagged'] for p in pts)} flagged")
    mt = m["match"]
    if mt:
        keys = ("spectrum_id", "best", "runner_up", "delta_chi2", "verdict", "confidence",
                "class", "type_range", "delta_class")
        print(json.dumps({k: mt[k] for k in keys}, indent=1))
        print("candidates:", [(c["type"], c["chi2"]) for c in mt["candidates"][:8]])
    else:
        print("match: null")
    print("measured_motion:", m["measured_motion"])
    print("overlays:", {k: len(v) for k, v in m["overlays"].items()})


if __name__ == "__main__":
    main(Path(sys.argv[1]))
