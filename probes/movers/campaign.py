"""Stages 2-3 data for one field, locally (the logic is pxs.movers.campaign; for the full
campaign use deploy/modal_movers.py). Usage:
    python probes/movers/campaign.py NAME RA DEC PASS_INDEX N_RUNS ["[x, y]" of a known TNO]
Writes cache/movers/campaign/<NAME>.npz and .json.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, "src")
from pxs.movers.campaign import run_field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
name, ra, dec, pidx, nruns = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), \
    int(sys.argv[4]), int(sys.argv[5])
known = tuple(json.loads(sys.argv[6])) if len(sys.argv) > 6 else None
data, meta = run_field(name, ra, dec, pidx, nruns, known)
out = Path("cache/movers/campaign")
out.mkdir(parents=True, exist_ok=True)
(out / f"{name}.npz").write_bytes(data)
(out / f"{name}.json").write_text(json.dumps(meta, indent=1))
print(json.dumps(meta))
