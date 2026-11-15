"""Build the star data behind web/explore.html.

Writes two files:
  web/data/stars.json                stars to V 6.5 (plus fainter stars that constellation lines use)
                                     from the Hipparcos Catalogue, positions moved to J2000.
  web/data/constellation-lines.json  constellation stick figures, IAU names and the proper names
                                     of bright stars, from Stellarium's "modern" sky culture.

Usage (stdlib only):
  python3 tools/star_chart/build.py [cache_dir]

Sources, fetched once into cache_dir (default: a temporary directory):
  Hipparcos main catalogue, ESA 1997, VizieR I/239/hip_main.dat, from the CfA VizieR mirror
  (vizier.cfa.harvard.edu; the CDS site was unreachable when this was written). The ESA Hipparcos
  data may be used freely with acknowledgement.
  Stellarium skycultures/modern/index.json (GitHub). Text and data: CC BY-SA 4.0, so the derived
  constellation-lines.json carries the same licence.

Positions are quantised to 0.001 degree (3.6 arcseconds), magnitudes and B-V to 0.1. Stars are
sorted brightest first, so the page can draw "everything brighter than m" as a prefix.
"""

import datetime as dt
import json
import math
import sys
import tempfile
import urllib.request
from pathlib import Path

HIP_URL = "https://vizier.cfa.harvard.edu/ftp/cats/I/239/hip_main.dat"
SKY_URL = "https://raw.githubusercontent.com/Stellarium/stellarium/master/skycultures/modern/index.json"
MAG_LIMIT = 6.5
EPOCH_SHIFT_YR = 2000.0 - 1991.25  # Hipparcos positions are for J1991.25
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "data"


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=300) as r:
            dest.write_bytes(r.read())
    return dest


def num(s: str):
    s = s.strip()
    return float(s) if s else None


def sexa_deg(text: str, hours: bool) -> float:
    parts = text.split()
    sign = -1 if parts[0].startswith("-") else 1
    v = abs(float(parts[0])) + float(parts[1]) / 60 + float(parts[2]) / 3600
    return sign * v * (15 if hours else 1)


def read_hipparcos(path: Path) -> dict:
    """HIP -> (ra, dec, vmag, bv) at J2000, for every star with a V magnitude."""
    stars = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        f = line.split("|")
        if len(f) < 38:
            continue
        hip, vmag = int(f[1]), num(f[5])
        if vmag is None:
            continue
        ra, dec = num(f[8]), num(f[9])
        if ra is None or dec is None:
            ra, dec = sexa_deg(f[3], True), sexa_deg(f[4], False)
        pmra, pmde = num(f[12]) or 0.0, num(f[13]) or 0.0
        cosd = max(math.cos(math.radians(dec)), 1e-6)
        ra = (ra + pmra * EPOCH_SHIFT_YR / 3.6e6 / cosd) % 360
        dec = max(-90.0, min(90.0, dec + pmde * EPOCH_SHIFT_YR / 3.6e6))
        stars[hip] = (ra, dec, vmag, num(f[37]))
    return stars


def main() -> None:
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    cache.mkdir(parents=True, exist_ok=True)
    hip = read_hipparcos(fetch(HIP_URL, cache / "hip_main.dat"))
    sky = json.loads(fetch(SKY_URL, cache / "modern.json").read_text(encoding="utf-8"))

    line_hips = {h for c in sky["constellations"] for poly in c["lines"] for h in poly if isinstance(h, int)}
    keep = sorted((h for h, s in hip.items() if s[2] <= MAG_LIMIT or h in line_hips), key=lambda h: (hip[h][2], h))
    index = {h: i for i, h in enumerate(keep)}

    def q(v, scale):
        return None if v is None else round(v * scale)

    stars = {
        "about": "Stars brighter than V 6.5, plus fainter stars used by constellation lines, brightest first.",
        "source": "Hipparcos Catalogue (ESA 1997), VizieR I/239/hip_main, via the CfA VizieR mirror",
        "licence": "ESA Hipparcos data, free to use with acknowledgement",
        "fetched": dt.date.today().isoformat(),
        "epoch": "J2000 (Hipparcos J1991.25 positions moved by their proper motions)",
        "units": {"ra": "0.001 deg", "dec": "0.001 deg", "mag": "0.1 mag (V)", "bv": "0.1 mag (B-V, null if unknown)"},
        "count": len(keep),
        "hip": keep,
        "ra": [q(hip[h][0], 1000) % 360000 for h in keep],
        "dec": [q(hip[h][1], 1000) for h in keep],
        "mag": [q(hip[h][2], 10) for h in keep],
        "bv": [q(hip[h][3], 10) for h in keep],
    }

    figures = []
    for c in sky["constellations"]:
        abbr = c["id"].split()[-1]
        polys = [[index[h] for h in poly if h in index] for poly in c["lines"]]
        figures.append({"abbr": abbr, "name": c["common_name"]["native"], "lines": [p for p in polys if len(p) > 1]})
    names = []
    for key, entries in sky.get("common_names", {}).items():
        h = int(key.split()[-1]) if key.startswith("HIP ") else None
        if h in index and hip[h][2] <= MAG_LIMIT:
            names.append([index[h], entries[0]["english"]])
    names.sort()
    lines = {
        "about": "Constellation stick figures and bright-star names; star numbers index web/data/stars.json.",
        "source": "Stellarium, skycultures/modern/index.json (github.com/Stellarium/stellarium)",
        "licence": "CC BY-SA 4.0 (Stellarium sky culture text and data)",
        "fetched": dt.date.today().isoformat(),
        "constellations": figures,
        "names": names,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("stars.json", stars), ("constellation-lines.json", lines)):
        path = OUT / name
        path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1024:.0f} KB")
    print(f"{len(keep)} stars, {len(figures)} constellations, {len(names)} named stars")


if __name__ == "__main__":
    main()
