"""CLI: python -m pxs.planetx [--out web/data/planetx-limits.json] [--gallery web/gallery]

Writes the Planet X limits table. The measured SPHEREx depth comes from the gallery manifests;
everything else is computed from the literature values cited in the module docstrings.
The output has no timestamp, so rerunning on unchanged inputs gives the same bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .depths import literature_depths, measured_channel_depth
from .table import build

ROOT = Path(__file__).resolve().parents[3]
# Faint gallery targets whose per-frame errors set the measured depth. Pinned so that new
# gallery entries do not silently change the table. Barnard's Star (saturated) and Eps Ind B
# (bright) are left out; the S/N < 5 cut in measured_channel_depth also drops bright points.
MEASURED_SLUGS = ("2mass-0415-0935", "denis-0255-4700", "ugps-0722-0540", "wise-0855-0714")


def render(gallery: Path) -> str:
    manifests = [json.loads((gallery / s / "manifest.json").read_text()) for s in MEASURED_SLUGS]
    depths = literature_depths()
    measured = measured_channel_depth(manifests)
    if measured.ab:
        depths.insert(2, measured)
    return json.dumps(build(depths), separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.planetx", description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "web/data/planetx-limits.json")
    ap.add_argument("--gallery", type=Path, default=ROOT / "web/gallery")
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.gallery))
    sys.stdout.write(f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
