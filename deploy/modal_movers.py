"""Mover-search validation campaign on Modal (pxs.movers.campaign), one container per unit.

    modal run deploy/modal_movers.py                      # every field, 8 injection runs each
    modal run deploy/modal_movers.py --only Haumea --runs 1

A unit is (field, "base") or (field, "runNN"). Each writes <field>__<unit>.npz/.json to the
Modal volume "pxs-movers" and commits it before returning a small plain dict, so results never
depend on unpickling numpy locally and a slow or failed unit loses nothing else. Units whose
JSON is already on the volume are skipped (rerun the same command to resume). Then:

    mkdir -p cache/movers/campaign/units
    modal volume get --force pxs-movers / cache/movers/campaign/units/   # trailing / needed
    uv run python -m pxs.movers.campaign merge cache/movers/campaign/units cache/movers/campaign

Failures are written to cache/movers/campaign/_failures.json. Separate app ("pxs-movers"); it
never touches the deployed pxs-lookup. Reads only public data; frame lookups use the
pxs-index volume, as the service does. This file must not import numpy or pxs at top level:
the local `modal` Python has neither.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modal_app import CACHE_ROOT, INDEX_MOUNT, image, index_volume

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "cache" / "movers" / "campaign"
RESULTS_MOUNT = "/results"
results_volume = modal.Volume.from_name("pxs-movers", create_if_missing=True)

# name: (ra, dec, pass index among usable passes, known TNO grid px or None). The TNO
# positions are from probes/movers/gate1.py (Horizons at mid-pass, 20' fields offset from the
# body); B1-B7 are blank high-latitude fields; the last two are targets.json high-proper-motion
# stars, artefact controls (they move < 1 px within a pass, so they must not be candidates).
# WISE 0855 uses pass 1: its pass 0 is 15 frames over 0.8 days, too short to test anything.
FIELDS: dict[str, tuple[float, float, int, tuple[float, float] | None]] = {
    "Haumea": (218.64096674077047, 15.037436666666666, 0, (127.0, 137.0)),
    "Makemake": (200.63287453322357, 21.04122, 2, (46.0, 119.0)),
    "Eris": (27.44204680308583, -0.16590999999981082, 0, (136.0, 68.0)),
    "B1": (160.0, 10.0, 0, None), "B2": (180.0, -5.0, 0, None), "B3": (30.0, 20.0, 0, None),
    "B4": (350.0, 5.0, 0, None), "B5": (230.0, -10.0, 0, None), "B6": (140.0, 25.0, 0, None),
    "B7": (10.0, -15.0, 0, None),
    "BarnardsStar": (269.4461566, 4.7696437, 0, None),
    "WISE0855": (133.7583173, -7.2419772, 1, None),
}

campaign_image = image.add_local_file(HERE / "modal_app.py", "/root/modal_app.py", copy=True)
app = modal.App("pxs-movers", image=campaign_image)


# The search is a single-threaded numpy loop (search._shifted_sum); 2 CPUs leave room for the
# threaded stamp reads. A 16-day pass has <= ~65k trials, about 2 min per search; a unit is
# one read plus two searches, so 1 h is ample margin.
@app.function(cpu=2.0, memory=8192, region="us-east", timeout=3600, max_containers=24,
              volumes={INDEX_MOUNT: index_volume.read_only(), RESULTS_MOUNT: results_volume},
              env={"PXS_CACHE": CACHE_ROOT, "PXS_SPHEREX_INDEX": INDEX_MOUNT,
                   "PXS_SPHEREX_INDEX_SIA_TAIL": "1"})
def unit(name: str, tag: str) -> dict:
    import logging
    import time
    import traceback

    from pxs.movers.campaign import base_unit, injection_unit

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    t0 = time.time()
    ra, dec, pidx, known = FIELDS[name]
    try:
        if tag == "base":
            data, meta = base_unit(name, ra, dec, pidx, known)
        else:
            data, meta = injection_unit(name, ra, dec, pidx, int(tag.removeprefix("run")))
        stem = Path(RESULTS_MOUNT) / f"{name}__{tag}"
        stem.with_suffix(".npz").write_bytes(data)
        stem.with_suffix(".json").write_text(json.dumps(meta))
        results_volume.commit()
        return {"name": name, "tag": tag, "ok": True, "seconds": float(time.time() - t0),
                "summary": json.dumps({k: meta.get(k) for k in (
                    "n_frames", "n_pass_frames", "n_trials", "search_s", "cpu_s", "real_ge7",
                    "null_ge7", "n_recovered", "n_injected")})}
    except Exception as e:  # noqa: BLE001 - one bad unit must not lose the others
        return {"name": name, "tag": tag, "ok": False, "seconds": float(time.time() - t0),
                "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-3000:]}


@app.local_entrypoint()
def main(only: str = "", runs: int = 8) -> None:
    names = [n for n in (only.split(",") if only else FIELDS) if n]
    unknown = [n for n in names if n not in FIELDS]
    if unknown:
        raise SystemExit(f"unknown fields: {unknown}; known: {list(FIELDS)}")
    done = {e.path.lstrip("/") for e in results_volume.listdir("/")}
    todo = [(n, t) for n in names for t in ["base"] + [f"run{r:02d}" for r in range(runs)]
            if f"{n}__{t}.json" not in done]
    print(f"{len(todo)} units to run ({len(names) * (runs + 1) - len(todo)} already done)")
    OUT.mkdir(parents=True, exist_ok=True)
    failures = {}
    for res in unit.starmap(todo, order_outputs=False, return_exceptions=True):
        if isinstance(res, BaseException):  # container timeout or crash
            failures[f"unknown-{len(failures)}"] = {"error": repr(res)[:2000]}
            print(f"a unit FAILED: {res!r}"[:500])
            continue
        if not res["ok"]:
            failures[f"{res['name']}__{res['tag']}"] = res
            print(f"{res['name']} {res['tag']}: FAILED {res['error']}")
            continue
        print(f"{res['name']} {res['tag']}: {res['seconds']:.0f} s {res['summary']}")
    (OUT / "_failures.json").write_text(json.dumps(failures, indent=1))
    print(f"{len(failures)} failures. Download: modal volume get --force pxs-movers / "
          f"cache/movers/campaign/units/ (mkdir it first)")
