"""Run the body-recovery campaign on Modal, one container per body.

    modal run tools/solarsystem_validation/modal_run.py --campaign smoke --only 136108,7733
    modal run tools/solarsystem_validation/modal_run.py --campaign v1
    modal volume get pxs-validation /v1 <local dir>

Ephemeral (`modal run`), never deployed. Frames come only from the local SPHEREx frame
index (volume `pxs-index`, read-only; no IRSA SIA tail), so the search stops at the
index's last observation and the run does not depend on IRSA's rate limits. Each
(body, variant) record is written to volume `pxs-validation` under /<campaign>/<pdes>/
via a temporary file and a rename, then committed. A rerun skips records whose status is
"ok" and retries the rest. Functions return only small dicts of plain Python types.
Containers that die (timeout, out of memory) are listed in <campaign>-failures.json locally.

Written with Claude Code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent.parent
APP = "/app"
INDEX_MOUNT = "/index/spherex"
RESULTS_MOUNT = "/results"
MAX_CONTAINERS = 16  # bounds the load on Horizons and on the S3 bucket
TIMEOUT_S = 3 * 3600
CPU = 4.0


def _image() -> modal.Image:
    base = modal.Image.from_registry("python:3.12-slim")
    if modal.is_local():
        sys.path.insert(0, str(REPO / "deploy"))
        from lock_requirements import export_requirements

        pins = export_requirements(REPO, REPO / "deploy" / ".build" / "requirements.txt")
        base = base.uv_pip_install(requirements=[str(pins)])
    return (base.env({"PYTHONPATH": f"{APP}/src:{APP}/tools", "PYTHONUNBUFFERED": "1"})
            .add_local_dir(REPO / "src", f"{APP}/src", ignore=["**/__pycache__"])
            .add_local_dir(REPO / "data", f"{APP}/data")
            .add_local_dir(REPO / "tools" / "solarsystem_validation",
                           f"{APP}/tools/solarsystem_validation", ignore=["**/__pycache__"]))


app = modal.App("pxs-body-recovery", image=_image())
index_volume = modal.Volume.from_name("pxs-index")
results = modal.Volume.from_name("pxs-validation", create_if_missing=True)


@app.function(cpu=CPU, memory=8192, timeout=TIMEOUT_S, max_containers=MAX_CONTAINERS,
              region="us-east", volumes={INDEX_MOUNT: index_volume.read_only(),
                                         RESULTS_MOUNT: results},
              env={"PXS_SPHEREX_INDEX": INDEX_MOUNT, "PXS_CACHE": "/tmp/pxs-cache",
                   "PXS_PROCESSES": str(int(CPU))})
def run_body(body: dict, campaign: str, provenance: dict) -> dict:
    """All variants of one body not yet recorded as ok; returns {pdes, status, wall_s}."""
    import logging

    from pxs.spherex import config as spx_config
    from pxs.spherex import localindex
    from solarsystem_validation.runbody import VARIANTS, run

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    results.reload()
    out = Path(RESULTS_MOUNT) / campaign / body["pdes"]
    pending = [v for v in VARIANTS if not _ok(out / f"{v}.json")]
    if not pending:
        return {"pdes": body["pdes"], "status": "already done", "wall_s": 0.0}
    idx = localindex.current()
    if idx is None:
        raise RuntimeError("the SPHEREx frame index is not mounted")
    rels = sorted(c.removeprefix("spherex_") for c in spx_config.COLLECTIONS)
    prov = {**provenance, "index_mjd_max": idx.max_mjd(rels),
            "index_releases": {r: {k: v for k, v in idx.manifest["releases"][r].items()
                                   if not isinstance(v, (dict, list))} for r in rels}}

    def write(variant: str, rec: dict) -> None:
        text = json.dumps(rec, allow_nan=False)
        out.mkdir(parents=True, exist_ok=True)
        tmp = out / f".{variant}.tmp"
        tmp.write_text(text)
        tmp.replace(out / f"{variant}.json")
        results.commit()

    status = run(body, prov["index_mjd_max"], pending, prov, write)
    return {"pdes": body["pdes"], "status": status, "wall_s": round(time.time() - t0, 1)}


def _ok(path: Path) -> bool:
    try:
        return json.loads(path.read_text()).get("status") == "ok"
    except (OSError, ValueError):
        return False


def _git() -> dict:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()

    return {"git_sha": git("rev-parse", "--short", "HEAD") or "unknown",
            "git_dirty": bool(git("status", "--porcelain"))}


@app.local_entrypoint()
def main(campaign: str = "v1", only: str = "") -> None:
    sample = json.loads((Path(__file__).with_name("sample.json")).read_text())
    bodies = sample["bodies"]
    if only:
        want = only.split(",")
        bodies = [b for b in bodies if b["pdes"] in want]
    prov = {**_git(), "campaign": campaign, "sample_drawn_utc": sample["drawn_utc"]}
    print(f"{len(bodies)} bodies, campaign {campaign}, {prov}")
    t0 = time.time()
    failures, wall = [], 0.0
    for body, r in zip(bodies, run_body.map(bodies, kwargs={"campaign": campaign,
                                                             "provenance": prov},
                                             return_exceptions=True)):
        if isinstance(r, BaseException):
            failures.append({"pdes": body["pdes"], "type": type(r).__name__,
                             "message": str(r)[:500]})
            print(f"{body['pdes']}: FAILED {type(r).__name__}: {str(r)[:200]}")
        else:
            wall += r["wall_s"]
            print(f"{r['pdes']}: {r['status']} in {r['wall_s']} s")
    Path(f"{campaign}-failures.json").write_text(json.dumps(failures, indent=1) + "\n")
    print(f"done in {time.time() - t0:.0f} s wall; {wall:.0f} container-s in completed "
          f"bodies; {len(failures)} container failures")
