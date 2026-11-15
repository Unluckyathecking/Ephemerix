"""Side-by-side montage of a body's sky-fixed flipbook frames (with the predicted position
circled) and its body-centred stacks, for the PR evidence.

    uv run python probes/solarsystem/montage.py <body dir with manifest.json> <out.png>
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(sys.argv[1])
m = json.loads((root / "manifest.json").read_text())
scale = 3
tiles = []
for f in m["frames"]:
    im = Image.open(root / f["image"]).convert("RGB")
    im = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
    if f["predicted_px"]:
        x, y = (v * scale for v in f["predicted_px"])
        ImageDraw.Draw(im).ellipse([x - 15, y - 15, x + 15, y + 15], outline=(255, 80, 80), width=2)
    ImageDraw.Draw(im).text((4, 4), f["date"][:16], fill=(255, 255, 0))
    tiles.append(im)
shown = m["solar_system"]["shown_pass"]
for f in m["solar_system"]["body_frames"]["frames"]:
    if f["id"].startswith(shown) and f["band"] in ("spx-b1", "spx-b2", "spx-b3"):
        im = Image.open(root / f["image"]).convert("RGB")
        im = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
        ImageDraw.Draw(im).text((4, 4), f"body-centred {f['band']} n={f['n_exposures']}",
                                fill=(120, 255, 120))
        tiles.append(im)
w = sum(t.width for t in tiles) + 4 * (len(tiles) - 1)
out = Image.new("RGB", (w, max(t.height for t in tiles)), (40, 40, 40))
x = 0
for t in tiles:
    out.paste(t, (x, 0))
    x += t.width + 4
out.save(sys.argv[2])
print("wrote", sys.argv[2], out.size)
