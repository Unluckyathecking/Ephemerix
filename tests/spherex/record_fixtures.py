"""Re-record the raw byte fixtures (needs network and the probe cache).

Usage: uv run python tests/spherex/record_fixtures.py /path/to/main/checkout/cache
Writes tests/spherex/fixtures/blocks/ (8 kB range-read blocks), stamps.json, and a
crop of the probe's stamp for the same frame (probe_crop.npz) for the bit-identity test.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

from pxs.spherex.net import BlockStore
from pxs.spherex.read import read_stamp

HERE = Path(__file__).parent / "fixtures"
BLOCK = 8192
HALF = 5
# (name, probe target, obs_id, detector)
FRAMES = [
    ("eps_d3", "eps_ind_b", "2025W39_2A_0693_3", 3),
    ("eps_d6", "eps_ind_b", "2025W39_2A_0693_3", 6),
    ("barnard", "barnard", None, None),
]


def main(probe_cache: Path) -> None:
    allframes = json.loads((probe_cache / "spherex_frames.json").read_text())
    store = BlockStore(root=HERE, block=BLOCK)
    out = {}
    for name, tgt, obs, det in FRAMES:
        stamps = sorted((probe_cache / "spherex_stamps" / tgt).glob("*.npz"))
        path = stamps[0] if obs is None else next(p for p in stamps if p.stem == f"{obs}_D{det}")
        obs, det = path.stem.rsplit("_D", 1)
        d = np.load(path)
        key = next(f["s3_key"] for f in allframes[tgt]
                   if f["obs_id"] == obs and f["detector"] == int(det))
        ra, dec = float(d["ra"]), float(d["dec"])
        for prefetch in (True, False):
            read_stamp(store, key, ra, dec, half=HALF, prefetch=prefetch)
        out[name] = {"key": key, "ra": ra, "dec": dec, "half": HALF, "block": BLOCK}
        if name == "eps_d3":
            c = slice(15 - HALF, 15 + HALF + 1)
            np.savez_compressed(HERE / "probe_crop.npz", image=d["image"][c, c],
                                flags=d["flags"][c, c], variance=d["variance"][c, c],
                                zodi=d["zodi"][c, c], psf=d["psf"], wave=d["wave"])
    (HERE / "stamps.json").write_text(json.dumps(out, indent=1))
    logging.getLogger(__name__).info("recorded %d GETs, %.2f MB", store.gets, store.bytes_fetched / 1e6)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(Path(sys.argv[1]))
