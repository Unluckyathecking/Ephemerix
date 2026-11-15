"""Learned-residual experiment on Modal: training cubes, training, and the gate.

    modal run tools/denoise/modal_denoise.py --stage build            # training cubes (CPU)
    modal run tools/denoise/modal_denoise.py --stage train --tag v1   # one GPU
    modal run tools/denoise/modal_denoise.py --stage smoke --tag v1   # gate code on a val field
    modal run tools/denoise/modal_denoise.py --stage shares --tag v1  # diagnostics, val fields
    modal run tools/denoise/modal_denoise.py --stage gate --tag v1    # the 12 campaign fields
    modal run tools/denoise/modal_denoise.py --stage select --tag v1  # follow-up: variance
    modal run tools/denoise/modal_denoise.py --stage fresh --tag v1 --variant smoothed
    modal volume get --force pxs-denoise /gate/v1/ cache/denoise/gate/ # then analyze.py

Everything is written to the volume "pxs-denoise" and committed before a function returns a
small plain dict; finished units are skipped on a rerun. Separate app ("pxs-denoise"); reads
only public data and the pxs-index volume. torch is installed in this file's image only. No
numpy, torch or pxs at top level: the local `modal` Python has none of them.
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

VOL = "/vol"
volume = modal.Volume.from_name("pxs-denoise", create_if_missing=True)
ENV = {"PXS_CACHE": CACHE_ROOT, "PXS_SPHEREX_INDEX": INDEX_MOUNT,
       "PXS_SPHEREX_INDEX_SIA_TAIL": "1"}

# Training fields: none within a degree of a gate field (deploy/modal_movers.py FIELDS).
# High galactic latitude first, then |b| of roughly 10-27 deg so crowded fields like the two
# control fields of the gate are represented. The last four are validation fields: used to
# pick the checkpoint and to smoke-test the gate code, never trained on.
TRAIN_FIELDS: dict[str, tuple[float, float]] = {
    "T01": (150.0, 30.0), "T02": (165.0, 20.0), "T03": (175.0, 5.0), "T04": (195.0, 12.0),
    "T05": (205.0, 0.0), "T06": (215.0, 30.0), "T07": (240.0, 20.0), "T08": (20.0, 5.0),
    "T09": (35.0, -10.0), "T10": (45.0, 10.0), "T11": (355.0, -20.0), "T12": (340.0, -5.0),
    "T13": (5.0, 25.0), "T14": (155.0, -5.0), "T15": (120.0, 40.0), "T16": (200.0, 40.0),
    "T17": (225.0, 10.0), "T18": (15.0, -30.0), "T19": (50.0, -20.0), "T20": (320.0, -15.0),
    "D01": (262.0, 0.0), "D02": (275.0, 15.0), "D03": (125.0, -15.0), "D04": (128.0, -2.0),
    "D05": (255.0, 8.0), "D06": (300.0, 0.0), "D07": (60.0, 15.0), "D08": (75.0, 5.0),
    "D09": (270.0, 25.0), "D10": (110.0, 5.0), "D11": (285.0, 30.0), "D12": (95.0, -25.0),
    "V01": (265.0, 10.0), "V02": (140.0, -12.0), "V03": (185.0, 25.0), "V04": (330.0, 10.0),
}
VAL_FIELDS = ["V01", "V02", "V03", "V04"]
# The gate: the 12 fields and passes of the validation campaign, copied from
# deploy/modal_movers.py FIELDS (importing that file here would define its app as well).
GATE_FIELDS: dict[str, tuple[float, float, int]] = {
    "Haumea": (218.64096674077047, 15.037436666666666, 0),
    "Makemake": (200.63287453322357, 21.04122, 2),
    "Eris": (27.44204680308583, -0.16590999999981082, 0),
    "B1": (160.0, 10.0, 0), "B2": (180.0, -5.0, 0), "B3": (30.0, 20.0, 0),
    "B4": (350.0, 5.0, 0), "B5": (230.0, -10.0, 0), "B6": (140.0, 25.0, 0),
    "B7": (10.0, -15.0, 0), "BarnardsStar": (269.4461566, 4.7696437, 0),
    "WISE0855": (133.7583173, -7.2419772, 1),
}
# Follow-up only (after the gate failed on flux): 12 fields never used for training,
# validation or the gate, to test one corrected variance choice. Pass: the first with a
# reference (pidx -1).
FRESH_FIELDS: dict[str, tuple[float, float, int]] = {
    "F01": (135.0, 45.0, -1), "F02": (170.0, 40.0, -1), "F03": (210.0, 20.0, -1),
    "F04": (190.0, -15.0, -1), "F05": (25.0, -25.0, -1), "F06": (345.0, 20.0, -1),
    "F07": (40.0, 30.0, -1), "F08": (245.0, 35.0, -1), "F09": (250.0, -5.0, -1),
    "F10": (120.0, 25.0, -1), "F11": (305.0, -20.0, -1), "F12": (65.0, -5.0, -1),
}
RUNS_PER_UNIT = 2

den_image = (image
             .pip_install("torch==2.5.1")
             .env({"PYTHONPATH": f"{APP_DIR}/src:{APP_DIR}/tools"})
             .add_local_file(REPO / "deploy" / "modal_app.py", "/root/modal_app.py", copy=True)
             .add_local_dir(HERE, f"{APP_DIR}/tools/denoise", copy=True,
                            ignore=["**/__pycache__", "**/*.pyc", "*.json", "*.md"]))
app = modal.App("pxs-denoise", image=den_image)


def _fail(name: str, tag: str, e: BaseException) -> dict:
    import traceback

    return {"name": name, "tag": tag, "ok": False, "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-3000:]}


@app.function(cpu=2.0, memory=12288, region="us-east", timeout=2400, max_containers=40,
              volumes={INDEX_MOUNT: index_volume.read_only(), VOL: volume}, env=ENV)
def build(name: str, ra: float, dec: float) -> dict:
    import logging

    from denoise.units import training_cubes

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        meta = training_cubes(name, ra, dec, Path(VOL) / "train")
        (Path(VOL) / "train" / f"{name}.json").write_text(json.dumps(meta))
        volume.commit()
        return {"name": name, "tag": "build", "ok": True, "summary": json.dumps(meta)}
    except Exception as e:  # noqa: BLE001 - one bad field must not lose the others
        return _fail(name, "build", e)


@app.function(gpu="A10G", cpu=4.0, memory=32768, timeout=3000, volumes={VOL: volume})
def train(tag: str, steps: int, lr: float) -> dict:
    from denoise.train import train as run

    out = run(Path(VOL) / "train", Path(VOL) / "run" / tag, VAL_FIELDS, steps=steps, lr=lr,
              on_epoch=volume.commit)
    volume.commit()
    return json.loads(json.dumps(out, default=float))


@app.function(cpu=4.0, memory=12288, region="us-east", timeout=3600, max_containers=40,
              volumes={INDEX_MOUNT: index_volume.read_only(), VOL: volume}, env=ENV)
def gate(name: str, ra: float, dec: float, pidx: int, tag: str, out_tag: str, unit: str,
         runs: list[int], mode: str = "gate") -> dict:
    """mode: "gate" (the registered arms), "select" (all variance choices), or one variance
    choice by name (arms base and den)."""
    import logging
    import time

    from denoise.units import (
        GATE_ARMS,
        SELECT_ARMS,
        gate_base,
        gate_injections,
        load_model,
        passes_to_use,
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    t0 = time.time()
    try:
        arms = {"gate": GATE_ARMS, "select": SELECT_ARMS}.get(mode, {"base": None, "den": mode})
        if pidx < 0:
            pidx = passes_to_use(ra, dec)[0]
        model = load_model(Path(VOL) / "run" / tag / "best.pt")
        res = gate_base(name, ra, dec, pidx, model, arms) if unit == "base" else \
            gate_injections(name, ra, dec, pidx, runs, model, arms)
        out = Path(VOL) / "gate" / out_tag
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}__{unit}.json").write_text(json.dumps(res))
        volume.commit()
        if unit == "base":
            summ = {a: {"null_ge7": sum(d[2] >= 7 for d in res[a]["null"]),
                        "null_ge5": len(res[a]["null"]),
                        "real_ge7": sum(d[2] >= 7 for d in res[a]["real"])}
                    for a in ("base", "den")} | {"stats": res["den"]["stats"]}
        else:
            summ = {a: sum((s[a]["snr"] or 0) >= 7 for s in res["sources"])
                    for a in ("base", "den")} | {"n": len(res["sources"])}
        return {"name": name, "tag": unit, "ok": True, "seconds": float(time.time() - t0),
                "summary": json.dumps(summ)}
    except Exception as e:  # noqa: BLE001
        return _fail(name, unit, e)


@app.function(cpu=4.0, memory=12288, region="us-east", timeout=1800, max_containers=8,
              volumes={INDEX_MOUNT: index_volume.read_only(), VOL: volume}, env=ENV)
def shares(name: str, ra: float, dec: float, tag: str) -> dict:
    from denoise.units import load_model, variance_shares

    try:
        probes = ((131, 84), (138, 89)) if name == "V03" else ()  # its two peaks >= 7
        res = variance_shares(name, ra, dec, 0, load_model(Path(VOL) / "run" / tag / "best.pt"),
                              probes)
        out = Path(VOL) / "shares" / tag
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.json").write_text(json.dumps(res))
        volume.commit()
        return {"name": name, "tag": "shares", "ok": True, "summary": json.dumps(res)}
    except Exception as e:  # noqa: BLE001
        return _fail(name, "shares", e)


def _report(results: object) -> None:
    failures = 0
    for res in results:
        if isinstance(res, BaseException):
            failures += 1
            print(f"a unit FAILED: {res!r}"[:500])
        elif not res["ok"]:
            failures += 1
            print(f"{res['name']} {res['tag']}: FAILED {res['error']}\n{res['trace'][-800:]}")
        else:
            print(f"{res['name']} {res['tag']}: {res.get('seconds', 0):.0f} s {res['summary']}")
    print(f"{failures} failures")


def _done(prefix: str) -> set[str]:
    try:
        return {e.path.rsplit("/", 1)[-1] for e in volume.listdir(prefix)}
    except Exception:  # noqa: BLE001 - the directory does not exist yet
        return set()


def _gate_units(fields: dict[str, tuple[float, float, int]], tag: str, out_tag: str,
                runs: int, mode: str = "gate") -> list:
    done = _done(f"/gate/{out_tag}")
    units = [("base", [])] + [(f"inj{k // RUNS_PER_UNIT:02d}",
                               list(range(k, min(k + RUNS_PER_UNIT, runs))))
                              for k in range(0, runs, RUNS_PER_UNIT)]
    return [(n, ra, dec, pidx, tag, out_tag, u, rr, mode)
            for n, (ra, dec, pidx) in fields.items()
            for u, rr in units if f"{n}__{u}.json" not in done]


@app.local_entrypoint()
def main(stage: str, tag: str = "v1", only: str = "", runs: int = 6, steps: int = 6000,
         lr: float = 2e-3, variant: str = "") -> None:
    pick = [n for n in only.split(",") if n]
    if stage == "build":
        done = _done("/train")
        todo = [(n, ra, dec) for n, (ra, dec) in TRAIN_FIELDS.items()
                if f"{n}.json" not in done and (not pick or n in pick)]
        print(f"{len(todo)} training fields to build")
        _report(build.starmap(todo, order_outputs=False, return_exceptions=True))
    elif stage == "train":
        out = train.remote(tag, steps, lr)
        for row in out["epochs"]:
            print(json.dumps(row))
        print(json.dumps({k: v for k, v in out.items() if k not in ("epochs", "train_files")}))
    elif stage == "smoke":
        ra, dec = TRAIN_FIELDS[pick[0] if pick else "V03"]
        todo = _gate_units({(pick[0] if pick else "V03"): (ra, dec, 0)}, tag, f"{tag}-smoke", 1)
        _report(gate.starmap(todo, order_outputs=False, return_exceptions=True))
    elif stage == "shares":  # validation fields only: what the model removes, and why
        todo = [(n, *TRAIN_FIELDS[n], tag) for n in VAL_FIELDS]
        _report(shares.starmap(todo, order_outputs=False, return_exceptions=True))
    elif stage == "gate":
        fields = {n: v for n, v in GATE_FIELDS.items() if not pick or n in pick}
        todo = _gate_units(fields, tag, tag, runs)
        print(f"{len(todo)} gate units to run")
        _report(gate.starmap(todo, order_outputs=False, return_exceptions=True))
    elif stage == "select":  # validation fields: every variance choice, 2 injection runs
        fields = {n: (*TRAIN_FIELDS[n], 0) for n in VAL_FIELDS}
        todo = _gate_units(fields, tag, f"{tag}-select", 2, "select")
        _report(gate.starmap(todo, order_outputs=False, return_exceptions=True))
    elif stage == "fresh":  # the follow-up test of one variance choice on fresh fields
        if variant not in ("pipeline", "smoothed", "reference_removed"):
            raise SystemExit("--variant: pipeline, smoothed or reference_removed")
        fields = {n: v for n, v in FRESH_FIELDS.items() if not pick or n in pick}
        todo = _gate_units(fields, tag, f"{tag}-fresh-{variant}", runs, variant)
        print(f"{len(todo)} follow-up units to run")
        _report(gate.starmap(todo, order_outputs=False, return_exceptions=True))
    else:
        raise SystemExit("stage: build, train, smoke, shares, gate, select or fresh")
