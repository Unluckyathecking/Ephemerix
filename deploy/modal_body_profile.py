"""Ephemeral timing run of the Solar System body pipeline on Modal, as the live service runs it.

    modal run deploy/modal_body_profile.py --body Haumea

Same image, CPU, memory and region as the service, with the SPHEREx frame index mounted
(PXS_SPHEREX_INDEX, PXS_SPHEREX_INDEX_SIA_TAIL=1) and empty data caches, so the run is
cold. Prints the manifest's `timings_s`, the wall time and the pass summary. A separate
app ("pxs-body-profile"); it never touches the deployed pxs-lookup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modal_app import APP_DIR, INDEX_MOUNT, PXS_PROCESSES, image, index_volume

profile_image = image.add_local_file(Path(__file__).resolve().parent / "modal_app.py",
                                     "/root/modal_app.py", copy=True)
app = modal.App("pxs-body-profile", image=profile_image)


@app.function(cpu=8.0, memory=8192, region="us-east", timeout=1500,
              volumes={INDEX_MOUNT: index_volume.read_only()})
def profile(body: str, processes: str = PXS_PROCESSES) -> dict:
    import os
    import subprocess
    import time

    env = {**os.environ, "PXS_CACHE": "/tmp/cache", "PXS_SPHEREX_INDEX": INDEX_MOUNT,
           "PXS_SPHEREX_INDEX_SIA_TAIL": "1", "PXS_PROCESSES": processes}
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, "-m", "pxs.solarsystem", "--body", body, "--out",
                          "/tmp/out"], env=env, cwd=APP_DIR, capture_output=True, text=True,
                         check=False)
    wall = round(time.perf_counter() - t0, 1)
    out = {"wall_s": wall, "returncode": res.returncode, "log_tail": res.stderr[-3000:]}
    for m in Path("/tmp/out").glob("*/manifest.json"):
        ss = json.loads(m.read_text())["solar_system"]
        out["timings_s"] = ss["timings_s"]
        out["frame_search"] = ss["frame_search"]
        out["passes"] = [(p["date_start"][:10], p["n_frames"], p["n_measured"], p["best_snr"])
                         for p in ss["passes"]]
    return out


@app.local_entrypoint()
def main(body: str = "Haumea", processes: str = PXS_PROCESSES) -> None:
    print(json.dumps(profile.remote(body, processes), indent=1))
