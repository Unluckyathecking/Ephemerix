"""WISE-to-SPHEREx handover: centroid minus predicted position (arcsec, east and north) for
the W2 frames of the last WISE years and every spx-b6 frame, and the jump between them.

    uv run python probes/assembly/handover.py <view dir> [...]

Grid x grows west and y grows south, so east = -dx and north = -dy (times arcsec/px).
Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def residuals(m: dict, band: str, since: float = 0.0) -> np.ndarray:
    s = m["fov_arcsec"] / m["size_px"]
    out = [(-(f["centroid_px"][0] - f["predicted_px"][0]) * s,
            -(f["centroid_px"][1] - f["predicted_px"][1]) * s)
           for f in m["frames"] if f["band"] == band and f["centroid_px"] and f["predicted_px"]
           and f["mjd"] >= since]
    return np.array(out).reshape(-1, 2)


def main(views: list[Path]) -> None:
    for view in views:
        m = json.loads((view / "manifest.json").read_text())
        w = residuals(m, "W2", since=59215.0)  # 2021 onwards
        x = residuals(m, "spx-b6")
        print(f"{view.name}: W2 2021-2024 n={len(w)} mean (E, N) {w.mean(0).round(2) if len(w) else '-'}"
              f" rms {w.std(0).round(2) if len(w) else '-'}; spx-b6 n={len(x)} mean "
              f"{x.mean(0).round(2) if len(x) else '-'} rms {x.std(0).round(2) if len(x) else '-'}")
        if len(w) and len(x):
            jump = x.mean(0) - w.mean(0)
            err = np.hypot(w.std(0) / np.sqrt(len(w)), x.std(0) / np.sqrt(max(len(x), 1)))
            print(f"  jump SPHEREx - WISE (E, N): {jump.round(2)} arcsec, +- {err.round(2)}")


if __name__ == "__main__":
    main([Path(a) for a in sys.argv[1:]])
