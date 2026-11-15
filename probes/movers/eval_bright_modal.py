"""Before/after evaluation of artefact fixes: campaign units under a named variant.

    modal run probes/movers/eval_bright_modal.py --variants base,halo --only BarnardsStar,B6 --runs 4

A variant patches pxs.movers (probes/movers/fix_variants.py) before the unit runs, then
runs pxs.movers.campaign.base_unit / injection_unit unchanged (same injection seeds, so
outcomes pair source by source). Results go to the separate volume "pxs-movers-eval" as
<variant>/<field>__<unit>.npz/.json; the campaign volume "pxs-movers" is never touched.
Units already on the volume are skipped. Download:

    modal volume get --force pxs-movers-eval / cache/movers/fixruns/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1] if len(HERE.parents) > 1 and (HERE.parents[1] / "deploy").is_dir() \
    else HERE
sys.path.insert(0, str(ROOT / "deploy") if ROOT != HERE else str(HERE))
from modal_app import CACHE_ROOT, INDEX_MOUNT, image, index_volume  # noqa: E402
from modal_movers import FIELDS  # noqa: E402

MOUNT = "/eval"
volume = modal.Volume.from_name("pxs-movers-eval", create_if_missing=True)
# name -> fix_variants.apply options. "base" is pxs.movers as committed.
VARIANTS: dict[str, dict[str, object]] = {
    "base": {},
    "static": {"static": True},
    "halo": {"halo_scale": 0.5},
    "static_halo": {"static": True, "halo_scale": 0.5},
    "frameweight": {"ref_weight": "frame"},
    "fw_halo": {"ref_weight": "frame", "halo_scale": 0.5},
}
eval_image = (image.add_local_file(ROOT / "deploy" / "modal_app.py", "/root/modal_app.py",
                                   copy=True)
              .add_local_file(ROOT / "deploy" / "modal_movers.py", "/root/modal_movers.py",
                              copy=True)
              .add_local_file(HERE / "fix_variants.py", "/root/fix_variants.py", copy=True))
app = modal.App("pxs-movers-eval", image=eval_image)


def _apply(opts: dict[str, object]) -> None:
    from fix_variants import apply
    apply(opts)


@app.function(cpu=2.0, memory=8192, region="us-east", timeout=3600, max_containers=40,
              volumes={INDEX_MOUNT: index_volume.read_only(), MOUNT: volume},
              env={"PXS_CACHE": CACHE_ROOT, "PXS_SPHEREX_INDEX": INDEX_MOUNT,
                   "PXS_SPHEREX_INDEX_SIA_TAIL": "1"})
def unit(variant: str, name: str, tag: str) -> dict:
    import logging
    import time
    import traceback

    logging.basicConfig(level=logging.INFO)
    t0 = time.time()
    try:
        _apply(VARIANTS[variant])
        from pxs.movers.campaign import base_unit, injection_unit
        ra, dec, pidx, known = FIELDS[name]
        if tag == "base":
            data, meta = base_unit(name, ra, dec, pidx, known)
        else:
            data, meta = injection_unit(name, ra, dec, pidx, int(tag.removeprefix("run")))
        out = Path(MOUNT) / variant
        out.mkdir(exist_ok=True)
        (out / f"{name}__{tag}.npz").write_bytes(data)
        (out / f"{name}__{tag}.json").write_text(json.dumps(meta | {"variant": variant}))
        volume.commit()
        return {"key": f"{variant}/{name}__{tag}", "ok": True, "s": time.time() - t0,
                "real_ge7": meta.get("real_ge7"), "null_ge7": meta.get("null_ge7"),
                "rec": meta.get("n_recovered")}
    except Exception as e:  # noqa: BLE001 - one failed unit must not lose the others
        return {"key": f"{variant}/{name}__{tag}", "ok": False, "s": time.time() - t0,
                "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}


@app.local_entrypoint()
def main(variants: str = "base", only: str = "BarnardsStar,WISE0855,Haumea,B6",
         runs: int = 4) -> None:
    done = set()
    for v in variants.split(","):
        try:
            done |= {f"{v}/{e.path.split('/')[-1]}" for e in volume.listdir(f"/{v}")}
        except Exception:  # noqa: BLE001 - directory not there yet
            pass
    todo = [(v, n, t) for v in variants.split(",") for n in only.split(",")
            for t in ["base"] + [f"run{r:02d}" for r in range(runs)]
            if f"{v}/{n}__{t}.json" not in done]
    print(f"{len(todo)} units to run")
    total = 0.0
    for res in unit.starmap(todo, order_outputs=False, return_exceptions=True):
        if isinstance(res, BaseException):
            print("FAILED", repr(res)[:300])
            continue
        total += res["s"]
        print(json.dumps({k: v for k, v in res.items() if k != "trace"})[:400])
        if not res["ok"]:
            print(res["trace"])
    print(f"container-seconds {total:.0f}")
