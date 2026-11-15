"""Ephemeral profiling run on Modal, same image, memory and region as the service.

    modal run deploy/modal_profile.py --target 2mass-0415-0935

Builds the view twice in one fresh container: cold (empty caches) then warm (stamp and query
caches from the first run kept), and returns both reports from deploy/profile_build.py.
CPU count: PXS_PROFILE_CPU (default 8, as the service since #28). PXS_PROFILE_SEED: a local
directory laid out like the cache (spherex/sia, wise/irsa, catalogs) whose archive-search
answers are copied in before the first run, for profiling while IRSA's search services are
down; it holds no image data, so image reads stay cold. This is a separate app
("pxs-profile"); it never touches the deployed pxs-lookup.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modal_app import APP_DIR, CACHE_ROOT, image

HERE = Path(__file__).resolve().parent
SEED_DIR = "/seed"
CPU = float(os.environ.get("PXS_PROFILE_CPU", "8"))
# The container imports this file again (from /root), so modal_app must be there too.
profile_image = (image
                 .add_local_file(HERE / "profile_build.py", f"{APP_DIR}/deploy/profile_build.py",
                                 copy=True)
                 .add_local_file(HERE / "modal_app.py", "/root/modal_app.py", copy=True)
                 .uv_pip_install("yappi==1.6.10"))  # CPU profile per thread (PXS_PROFILE_YAPPI)
if os.environ.get("PXS_PROFILE_SEED"):
    profile_image = profile_image.add_local_dir(os.environ["PXS_PROFILE_SEED"], SEED_DIR,
                                                copy=True)
app = modal.App("pxs-profile", image=profile_image)


def _seed() -> None:
    import shutil

    seed = Path(SEED_DIR)
    if not seed.exists():
        return
    for f in seed.rglob("*"):
        if f.is_file():
            dest = Path(CACHE_ROOT) / f.relative_to(seed)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)  # a fresh mtime, so the SPHEREx SIA answer is not stale


@app.function(cpu=CPU, memory=8192, region="us-east", timeout=1200)
def profile(target: str, runs: int = 2, yappi: bool = False, procs: int = 0) -> list[dict]:
    import subprocess

    _seed()
    env = {**os.environ, "PXS_CACHE": CACHE_ROOT, "PXS_WISE_CACHE": f"{CACHE_ROOT}/wise",
           "PXS_PROFILE_YAPPI": "1" if yappi else "0", "PXS_PROCESSES": str(procs)}
    out = []
    for i in range(runs):
        res = subprocess.run(
            [sys.executable, f"{APP_DIR}/deploy/profile_build.py", "--target", target,
             "--out", f"/tmp/prof{i}"],
            env=env, cwd=APP_DIR, capture_output=True, text=True, check=False)
        if res.returncode:
            out.append({"error": res.stderr[-4000:]})
            continue
        out.append(json.loads(res.stdout))
    return out


@app.local_entrypoint()
def main(target: str = "2mass-0415-0935", runs: int = 2, yappi: bool = False,
         procs: int = 0) -> None:
    reports = profile.remote(target, runs, yappi, procs)
    path = Path("deploy/.build") / f"profile-{target}-p{procs}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reports, indent=1) + "\n")
    print(json.dumps([{k: v for k, v in r.items() if k != "manifest"} for r in reports],
                     indent=1))
