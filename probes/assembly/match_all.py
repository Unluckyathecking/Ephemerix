"""Type every spectrum of a built view (each pass and the combined one) and print the result.

    uv run python probes/assembly/match_all.py <view dir> [...]

Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from pxs.typegate import detected, faint_reason
from pxs.typing import match_spectrum


def main(views: list[Path]) -> None:
    for view in views:
        m = json.loads((view / "manifest.json").read_text())
        print(f"\n{view.name}: manifest match on {(m['match'] or {}).get('spectrum_id')}")
        for s in m["spectra"]:
            pts = [p for p in s["points"] if p["flux"] is not None and p["err"] is not None]
            snr = np.median([p["flux"] / p["err"] for p in pts if not p["flagged"]])
            r = match_spectrum([p["wl_um"] for p in pts], [p["flux"] for p in pts],
                               [p["err"] for p in pts], [p["flagged"] for p in pts])
            det = detected(s)
            print(f"  {s['id']:9s} gate: {len(det)} points at S/N >= 3 on arrays "
                  f"{sorted({p['detector'] for p in det})} -> {faint_reason(s) or 'passes'}")
            if r is None:
                print(f"  {s['id']}: no match ({len(pts)} points)")
                continue
            b = r["best"]
            print(f"  {s['id']:9s} n={b['dof'] + 1:3d} medS/N={snr:6.1f} best {b['type']:13s} "
                  f"chi2/dof={b['chi2'] / b['dof']:6.2f} range {r['type_range']} "
                  f"class {r['class']} ({r['confidence']}, dclass {r['delta_class']})")


if __name__ == "__main__":
    main([Path(a) for a in sys.argv[1:]])
