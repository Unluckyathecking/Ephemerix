"""Check 2 correctness: S3 stamp == IRSA server-side cutout of the same frame."""
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits

from stamp import read_stamp
from targets import coord_at

CACHE = Path(__file__).resolve().parents[2] / "cache"
UA = {"User-Agent": "planet-x-spherex-probe"}


def main(target: str = "r_dra", idx: int = 3) -> None:
    f = [x for x in json.load(open(CACHE / "spherex_frames.json"))[target]
         if x["collection"] == "spherex_dr1"][idx]
    c = coord_at(target, f["mjd"])
    t = time.time()
    s = read_stamp(f["s3_key"], c.ra.deg, c.dec.deg)
    print(f"S3 stamp: {time.time() - t:.2f}s, {s.bytes_read / 1e6:.2f} MB")
    t = time.time()
    r = requests.get(f["url"], params={"center": f"{c.ra.deg},{c.dec.deg}", "size": "31pix"},
                     headers=UA, timeout=120)
    r.raise_for_status()
    print(f"IRSA cutout: {time.time() - t:.2f}s, {len(r.content) / 1e6:.2f} MB")
    h = fits.open(io.BytesIO(r.content))
    h.info()
    for ext in ["IMAGE", "FLAGS", "VARIANCE", "ZODI"]:
        cut = h[ext].data
        hdr = h[ext].header
        # CRVAL1A/2A = 0-based full-frame pixel of the cutout's pixel CRPIX1A/2A
        cx0 = int(round(hdr["CRVAL1A"] - (hdr["CRPIX1A"] - 1)))
        cy0 = int(round(hdr["CRVAL2A"] - (hdr["CRPIX2A"] - 1)))
        mine = getattr(s, ext.lower())
        # overlap in full-frame coordinates
        xa, xb = max(cx0, s.x0), min(cx0 + cut.shape[1], s.x0 + mine.shape[1])
        ya, yb = max(cy0, s.y0), min(cy0 + cut.shape[0], s.y0 + mine.shape[0])
        a = cut[ya - cy0:yb - cy0, xa - cx0:xb - cx0]
        b = mine[ya - s.y0:yb - s.y0, xa - s.x0:xb - s.x0]
        same = np.array_equal(a, b, equal_nan=True) if ext != "FLAGS" else np.array_equal(a, b)
        print(f"{ext:9s} cutout origin ({cx0},{cy0}) stamp origin ({s.x0},{s.y0}) "
              f"overlap {a.shape} identical={same}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
