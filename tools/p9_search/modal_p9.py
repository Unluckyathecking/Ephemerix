"""Planet Nine region pilot search on Modal.

    modal run tools/p9_search/modal_p9.py --stage preflight            # passes of 48 tiles
    modal run tools/p9_search/modal_p9.py --stage search --n 32 --runs 4
    modal volume get --force pxs-movers /p9/ cache/p9/units/          # then report.py

Pre-flight queries only the frame index for each ranked tile in tiles.json and writes
preflight.json next to this file (committed: it fixes which pass each tile searches). The
search takes the first N ranked tiles whose pre-flight found a pass with a reference, and
runs one base unit (real search, mirrored null, labelled peaks, stamps) and `runs` injection
units per tile, each in its own container. Units write p9/<tile>__<unit>.json to the volume
"pxs-movers" (stamps under p9/stamps/) and commit before returning a small plain dict.
Units already on the volume are skipped, so rerunning resumes. Separate app name
("pxs-p9-search"); nothing outside p9/ is written. No numpy or pxs at top level: the local
`modal` Python has neither.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "deploy"))
from modal_app import APP_DIR, CACHE_ROOT, INDEX_MOUNT, image, index_volume

RESULTS_MOUNT = "/results"
PREFIX = "p9"
results_volume = modal.Volume.from_name("pxs-movers", create_if_missing=True)
ENV = {"PXS_CACHE": CACHE_ROOT, "PXS_SPHEREX_INDEX": INDEX_MOUNT,
       "PXS_SPHEREX_INDEX_SIA_TAIL": "1"}

p9_image = (image
            .env({"PYTHONPATH": f"{APP_DIR}/src:{APP_DIR}/tools"})
            .add_local_file(REPO / "deploy" / "modal_app.py", "/root/modal_app.py", copy=True)
            .add_local_dir(HERE, f"{APP_DIR}/tools/p9_search", copy=True,
                           ignore=["**/__pycache__", "**/*.pyc", "*.json"]))
app = modal.App("pxs-p9-search", image=p9_image)


@app.function(cpu=1.0, memory=2048, region="us-east", timeout=900, max_containers=16,
              volumes={INDEX_MOUNT: index_volume.read_only()}, env=ENV)
def preflight(name: str, ra: float, dec: float) -> dict:
    import traceback

    from p9_search.unit import preflight as run

    try:
        return {"name": name, "ok": True} | run(ra, dec)
    except Exception as e:  # noqa: BLE001 - one bad tile must not lose the others
        return {"name": name, "ok": False, "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-2000:], "chosen": None}


# As deploy/modal_movers.py: one read plus one or two searches per unit, single-threaded numpy.
@app.function(cpu=2.0, memory=8192, region="us-east", timeout=3600, max_containers=24,
              volumes={INDEX_MOUNT: index_volume.read_only(), RESULTS_MOUNT: results_volume},
              env=ENV)
def unit(name: str, ra: float, dec: float, pidx: int, tag: str) -> dict:
    import logging
    import time
    import traceback

    from p9_search.unit import base_unit, injection_unit

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    t0 = time.time()
    root = Path(RESULTS_MOUNT) / PREFIX
    try:
        if tag == "base":
            meta = base_unit(name, ra, dec, pidx, stamp_dir=root / "stamps")
        else:
            meta = injection_unit(name, ra, dec, pidx, int(tag.removeprefix("run")))
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{name}__{tag}.json").write_text(json.dumps(meta))
        results_volume.commit()
        keys = ("n_frames", "n_pass_frames", "n_trials", "search_s", "null_max",
                "d_motion_au", "n_recovered", "n_injected")
        return {"name": name, "tag": tag, "ok": True, "seconds": float(time.time() - t0),
                "summary": json.dumps({k: meta.get(k) for k in keys}),
                "n_peaks": len(meta.get("peaks_ge7", []))}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "tag": tag, "ok": False, "seconds": float(time.time() - t0),
                "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-3000:]}


def _tiles() -> list[dict]:
    return json.loads((HERE / "tiles.json").read_text())["tiles"]


def _run_preflight() -> None:
    tiles = _tiles()
    res = {r["name"]: r for r in preflight.starmap(
        [(t["name"], t["ra"], t["dec"]) for t in tiles], order_outputs=False)}
    out = [t | {"preflight": res[t["name"]]} for t in tiles]
    (HERE / "preflight.json").write_text(json.dumps(out, indent=1) + "\n")
    good = sum(r["chosen"] is not None for r in res.values())
    print(f"{good}/{len(tiles)} tiles have a usable pass with a reference")
    for t in out:
        p = t["preflight"]
        print(t["name"], p.get("chosen"), p.get("error", ""),
              [(q["n_window"], round(q["window_days"], 1)) for q in p.get("passes", [])])


def _run_search(n: int, runs: int) -> None:
    rows = json.loads((HERE / "preflight.json").read_text())
    chosen = [t for t in rows if t["preflight"]["chosen"] is not None][:n]
    done = {e.path.rsplit("/", 1)[-1] for e in results_volume.listdir(f"/{PREFIX}")} \
        if _exists(PREFIX) else set()
    todo = [(t["name"], t["ra"], t["dec"], t["preflight"]["chosen"], tag)
            for t in chosen for tag in ["base"] + [f"run{r:02d}" for r in range(runs)]
            if f"{t['name']}__{tag}.json" not in done]
    print(f"{len(chosen)} tiles; {len(todo)} units to run "
          f"({len(chosen) * (runs + 1) - len(todo)} already done)")
    failures, seconds = {}, 0.0
    for res in unit.starmap(todo, order_outputs=False, return_exceptions=True):
        if isinstance(res, BaseException):
            failures[f"unknown-{len(failures)}"] = {"error": repr(res)[:2000]}
            print(f"a unit FAILED: {res!r}"[:500])
            continue
        seconds += res["seconds"]
        if not res["ok"]:
            failures[f"{res['name']}__{res['tag']}"] = res
            print(f"{res['name']} {res['tag']}: FAILED {res['error']}")
            continue
        print(f"{res['name']} {res['tag']}: {res['seconds']:.0f} s {res['summary']}")
    out = REPO / "cache" / "p9"
    out.mkdir(parents=True, exist_ok=True)
    (out / "_failures.json").write_text(json.dumps(failures, indent=1))
    print(f"{len(failures)} failures; {seconds / 3600:.2f} container-hours this run")


def _exists(prefix: str) -> bool:
    return any(e.path.strip("/") == prefix for e in results_volume.listdir("/"))


@app.local_entrypoint()
def main(stage: str = "preflight", n: int = 32, runs: int = 4) -> None:
    if stage == "preflight":
        _run_preflight()
    elif stage == "search":
        _run_search(n, runs)
    else:
        raise SystemExit("--stage preflight|search")
