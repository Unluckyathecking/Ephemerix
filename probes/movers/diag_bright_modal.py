"""Run diag_bright.diagnose on Modal for campaign fields; writes cache/movers/diag/<field>.npz.

    modal run probes/movers/diag_bright_modal.py --only BarnardsStar,WISE0855,Haumea,B6
    modal run probes/movers/diag_bright_modal.py --variant frameweight   # -> diag/<variant>/
--variant applies one of eval_bright_modal.VARIANTS (fix_variants patches) before the run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
# Locally the repository root is two levels up; in the container this file sits in /root
# next to modal_app.py and modal_movers.py.
ROOT = HERE.parents[1] if len(HERE.parents) > 1 and (HERE.parents[1] / "deploy").is_dir() \
    else HERE
sys.path.insert(0, str(ROOT / "deploy") if ROOT != HERE else str(HERE))
from modal_app import APP_DIR, CACHE_ROOT, INDEX_MOUNT, image, index_volume  # noqa: E402
from modal_movers import FIELDS  # noqa: E402

OUT = ROOT / "cache" / "movers" / "diag"
diag_image = (image.add_local_file(ROOT / "deploy" / "modal_app.py", "/root/modal_app.py", copy=True)
              .add_local_file(ROOT / "deploy" / "modal_movers.py", "/root/modal_movers.py",
                              copy=True)
              .add_local_file(Path(__file__).with_name("diag_bright.py"),
                              f"{APP_DIR}/diag_bright.py", copy=True)
              .add_local_file(Path(__file__).with_name("eval_bright_modal.py"),
                              "/root/eval_bright_modal.py", copy=True)
              .add_local_file(Path(__file__).with_name("fix_variants.py"),
                              "/root/fix_variants.py", copy=True))
app = modal.App("pxs-movers-diag", image=diag_image)


@app.function(cpu=2.0, memory=16384, region="us-east", timeout=3600,
              volumes={INDEX_MOUNT: index_volume.read_only()},
              env={"PXS_CACHE": CACHE_ROOT, "PXS_SPHEREX_INDEX": INDEX_MOUNT,
                   "PXS_SPHEREX_INDEX_SIA_TAIL": "1"})
def run(name: str, variant: str = "") -> tuple[str, bytes]:
    import logging
    sys.path.insert(0, APP_DIR)
    if variant:
        from eval_bright_modal import VARIANTS, _apply
        _apply(VARIANTS[variant])
    from diag_bright import diagnose
    logging.basicConfig(level=logging.INFO)
    ra, dec, pidx, _ = FIELDS[name]
    return name, diagnose(ra, dec, pidx)


@app.local_entrypoint()
def main(only: str = "BarnardsStar,WISE0855,Haumea,B6", variant: str = "") -> None:
    out = OUT / variant if variant else OUT
    out.mkdir(parents=True, exist_ok=True)
    names = only.split(",")
    for name, data in run.map(names, [variant] * len(names), order_outputs=False):
        (out / f"{name}.npz").write_bytes(data)
        print(name, len(data) // 1_000_000, "MB")
