"""Compact contact sheet of a built view: an 80" crop around the target in each frame, 2x,
predicted position as a red ring and the centroid as a green cross.

    uv run python probes/astro/target_sheet.py <view dir> <out.png> [band ...]

Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HALF, ZOOM, COLS, CAP = 40, 2, 8, 14


def tile(view: Path, f: dict, centre: tuple[float, float]) -> Image.Image:
    img = Image.open(view / f["image"]).convert("RGB")
    cx, cy = int(centre[0]), int(centre[1])
    img = img.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF))
    img = img.resize((img.width * ZOOM, img.height * ZOOM), Image.Resampling.NEAREST)
    out = Image.new("RGB", (img.width, img.height + CAP), (20, 20, 30))
    out.paste(img, (0, CAP))
    d = ImageDraw.Draw(out)

    def at(p):
        return (p[0] - cx + HALF) * ZOOM, (p[1] - cy + HALF) * ZOOM + CAP

    if f["predicted_px"]:
        x, y = at(f["predicted_px"])
        d.ellipse([x - 10, y - 10, x + 10, y + 10], outline=(255, 60, 60))
    if f["centroid_px"]:
        x, y = at(f["centroid_px"])
        d.line([x - 6, y, x + 6, y], fill=(60, 255, 60))
        d.line([x, y - 6, x, y + 6], fill=(60, 255, 60))
    d.text((3, 1), f["id"] + ("" if f["centroid_px"] else " (no centroid)"), fill=(230, 230, 230))
    return out


def main(view: Path, out: Path, bands: list[str]) -> None:
    m = json.loads((view / "manifest.json").read_text())
    frames = [f for f in m["frames"] if not bands or f["band"] in bands]
    size = m["size_px"]
    tiles = [tile(view, f, f["predicted_px"] or (size / 2, size / 2)) for f in frames]
    w, h = tiles[0].size
    rows = -(-len(tiles) // COLS)
    sheet = Image.new("RGB", (w * COLS, h * rows))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % COLS) * w, (i // COLS) * h))
    sheet.save(out, optimize=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
