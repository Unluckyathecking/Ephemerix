"""Contact sheet of a built view, for checking frames by eye.

    uv run python probes/assembly/contact_sheet.py <view dir> <out.png> [band ...]

Each frame PNG is enlarged 3x with the predicted position as a red ring and the measured
centroid as a green cross; the caption gives id, warnings and |centroid - predicted| in
grid pixels. Written with Claude Code.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ZOOM = 3
COLS = 4
CAPTION = 30
log = logging.getLogger("contact_sheet")


def tile(view: Path, f: dict) -> Image.Image:
    img = Image.open(view / f["image"]).convert("RGB")
    img = img.resize((img.width * ZOOM, img.height * ZOOM), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (img.width, img.height + CAPTION), (20, 20, 30))
    canvas.paste(img, (0, CAPTION))
    d = ImageDraw.Draw(canvas)
    off = "-"
    if f["predicted_px"]:
        x, y = (v * ZOOM for v in f["predicted_px"])
        d.ellipse([x - 12, y + CAPTION - 12, x + 12, y + CAPTION + 12], outline=(255, 60, 60))
    if f["centroid_px"]:
        x, y = (v * ZOOM for v in f["centroid_px"])
        d.line([x - 8, y + CAPTION, x + 8, y + CAPTION], fill=(60, 255, 60))
        d.line([x, y + CAPTION - 8, x, y + CAPTION + 8], fill=(60, 255, 60))
        if f["predicted_px"]:
            off = f"{math.dist(f['centroid_px'], f['predicted_px']):.1f}px"
    d.text((4, 2), f"{f['id']} n={f['n_exposures']} off={off}", fill=(230, 230, 230))
    d.text((4, 15), ",".join(f["warnings"])[:60], fill=(255, 200, 120))
    return canvas


def main(view: Path, out: Path, bands: list[str]) -> None:
    m = json.loads((view / "manifest.json").read_text())
    frames = [f for f in m["frames"] if not bands or f["band"] in bands]
    tiles = [tile(view, f) for f in frames]
    w, h = tiles[0].size
    rows = math.ceil(len(tiles) / COLS)
    sheet = Image.new("RGB", (w * COLS, h * rows), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % COLS) * w, (i // COLS) * h))
    sheet.save(out)
    log.info("wrote %s (%d frames)", out, len(tiles))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
