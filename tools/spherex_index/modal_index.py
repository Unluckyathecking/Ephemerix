"""Run the SPHEREx frame indexer on Modal, in us-east-1 next to the bucket.

    modal run tools/spherex_index/modal_index.py --weeks dr1/2025W17_4B     # one week
    modal run tools/spherex_index/modal_index.py                            # everything new

Ephemeral (`modal run`), never deployed. One function call per week directory, mapped over
at most MAX_CONTAINERS containers; the total request rate to the bucket is capped at
TOTAL_RPS split evenly. Output goes to the volume `pxs-index` (rows/, failed/, manifest.json,
and cache-v1.npz, the one-file copy the lookup service loads).
Re-running only reads files that are not yet in the index. Download with:

    modal volume get pxs-index / cache/spherex_index
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent.parent
VOLUME_NAME = "pxs-index"
MOUNT = "/index"
MAX_CONTAINERS = 12
TOTAL_RPS = 300.0  # all containers together, requests per second to the bucket
WORKERS = 6

app = modal.App("pxs-spherex-index")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("astropy>=6", "numpy", "scipy", "requests", "pyvo", "fsspec", "s3fs", "aiohttp",
                 "reproject>=0.21.0", "pillow", "pyarrow")
    .env({"PYTHONPATH": "/root/src:/root/tools"})
    .add_local_dir(str(REPO / "src" / "pxs"), "/root/src/pxs")
    .add_local_dir(str(REPO / "tools" / "spherex_index"), "/root/tools/spherex_index")
)


@app.function(image=image, volumes={MOUNT: volume}, region="us-east", cpu=1.0, memory=1536,
              timeout=4 * 3600, max_containers=MAX_CONTAINERS, retries=modal.Retries(max_retries=2))
def index_week(release: str, week: str, max_rps: float, workers: int = WORKERS) -> dict:
    """Index one week directory into the volume; returns the run's counters."""
    import logging
    from dataclasses import asdict

    from spherex_index.build_index import index_week as run

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    volume.reload()
    counters = run(Path(MOUNT), release, week, max_rps=max_rps, workers=workers,
                   on_chunk=volume.commit)
    volume.commit()
    return {"release": release, "week": week, **asdict(counters)}


@app.function(image=image, region="us-east", timeout=600)
def plan() -> list[tuple[str, str]]:
    """Every (release, week) directory of the configured releases."""
    from spherex_index.build_index import Counters, Fetcher, list_weeks, releases

    f = Fetcher(5.0, Counters())
    return [(r, w) for r in releases() for w in list_weeks(f, r)]


@app.function(image=image, volumes={MOUNT: volume}, region="us-east", timeout=1800,
              memory=4096)  # the cache build holds the whole index twice (about 1.1 GB peak)
def finalize(code_version: str) -> dict:
    """Write manifest.json, then the load cache keyed to it, from the shards on the volume."""
    from pxs.spherex.localindex import write_cache
    from spherex_index.build_index import write_manifest

    volume.reload()
    manifest = write_manifest(Path(MOUNT), code_version)
    write_cache(Path(MOUNT))
    volume.commit()
    return {k: v for k, v in manifest.items() if k != "releases"} | {
        "per_release": {r: {k: v for k, v in d.items() if k != "per_week"}
                        for r, d in manifest["releases"].items()}}


@app.local_entrypoint()
def main(weeks: str = "", containers: int = MAX_CONTAINERS, total_rps: float = TOTAL_RPS,
         summary: str = "") -> None:
    """Index the given release/week list (comma separated), or every week when empty."""
    if weeks:
        pairs = [tuple(w.split("/", 1)) for w in weeks.split(",")]
    else:
        pairs = plan.remote()
    containers = max(1, min(containers, len(pairs), MAX_CONTAINERS))
    per = total_rps / containers
    print(f"{len(pairs)} week directories, {containers} containers, {per:.1f} req/s each")
    results = list(index_week.starmap([(r, w, per) for r, w in pairs]))
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                         text=True, check=False).stdout.strip() or "unknown"
    manifest = finalize.remote(sha)
    totals = {k: sum(r[k] for r in results) for k in
              ("requests", "bytes_read", "retries", "widened", "rows", "failed", "skipped")}
    totals["max_container_seconds"] = max(r["seconds"] for r in results)
    totals["sum_container_seconds"] = sum(r["seconds"] for r in results)
    out = {"totals": totals, "manifest": manifest, "weeks": results}
    print(json.dumps({"totals": totals, "manifest_rows": manifest["rows"],
                      "failed": manifest["failed"]}, indent=1))
    if summary:
        Path(summary).write_text(json.dumps(out, indent=1))
