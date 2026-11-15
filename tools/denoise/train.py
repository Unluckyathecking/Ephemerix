"""Self-supervised training of the residual model (GPU, on Modal).

Each sample is a random crop of one search frame. The target is the frame's whitened
difference image; the model sees the references (other passes) everywhere and the frame
itself only outside the blind hole, so input and target noise are independent and the
minimiser is the predictable part of the difference image: the reference's own noise,
static-sky residuals, and structure extended beyond the hole. Loss: Huber on valid pixels
(single-frame outliers such as cosmic rays are not predictable and must not dominate). An
"epoch" is EPOCH_STEPS steps; after each one the validation loss is measured on fields held
out of training (never the gate fields) and checkpoints and the log are written through
`on_epoch`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

EPOCH_STEPS = 500
HUBER_DELTA = 3.0
STAR_SIGMA = 3.0  # "on a star": deep reference brighter than this many frame sigma


def _load(files: list[Path]) -> tuple[Any, Any]:
    import numpy as np
    import torch

    xs, ss = [], []
    for f in files:
        with np.load(f) as z:
            xs.append(z["x"])
            ss.append(z["scal"])
    return torch.from_numpy(np.concatenate(xs)), torch.from_numpy(np.concatenate(ss))


def _losses(model: Any, x: Any, scal: Any) -> dict[str, float]:
    """Validation sums over whole frames: Huber and squared error for g and for g = 0, over
    all valid pixels and over star pixels, with squared error on |t| < 5 only."""
    import torch
    from torch.nn.functional import huber_loss

    tot = {k: 0.0 for k in ("hub", "hub0", "se", "se0", "n", "sse", "sse0", "sn")}
    model.eval()
    with torch.no_grad():
        for i in range(0, len(x), 32):
            xb = x[i:i + 32].cuda().float()
            g = model(xb, scal[i:i + 32].cuda())
            t, ok = xb[:, 0], xb[:, 1] > 0
            core = ok & (t.abs() < 5)
            star = core & (torch.sinh(xb[:, 3].abs()) > STAR_SIGMA)
            zero = torch.zeros_like(t)
            tot["hub"] += float(huber_loss(g[ok], t[ok], reduction="sum", delta=HUBER_DELTA))
            tot["hub0"] += float(huber_loss(zero[ok], t[ok], reduction="sum", delta=HUBER_DELTA))
            tot["se"] += float(((g - t)[core] ** 2).sum())
            tot["se0"] += float((t[core] ** 2).sum())
            tot["n"] += float(core.sum())
            tot["sse"] += float(((g - t)[star] ** 2).sum())
            tot["sse0"] += float((t[star] ** 2).sum())
            tot["sn"] += float(star.sum())
    model.train()
    return {"val_huber": tot["hub"] / max(tot["n"], 1), "val_huber_zero": tot["hub0"] / max(
        tot["n"], 1), "ev_all": 1 - tot["se"] / tot["se0"],
        "ev_star": 1 - tot["sse"] / max(tot["sse0"], 1e-9),
        "star_fraction": tot["sn"] / max(tot["n"], 1)}


def train(data_dir: Path, out_dir: Path, val_fields: list[str], steps: int = 6000,
          batch: int = 64, crop: int = 96, lr: float = 2e-3, seed: int = 0,
          on_epoch: Callable[[], None] | None = None) -> dict[str, Any]:
    import torch
    from torch.nn.functional import huber_loss

    from .model import blind_check, build_model, n_params

    t0 = time.time()
    torch.manual_seed(seed)
    files = sorted(data_dir.glob("*.npz"))
    is_val = [f.name.split("__")[0] in val_fields for f in files]
    xt, st = _load([f for f, v in zip(files, is_val, strict=True) if not v])
    xv, sv = _load([f for f, v in zip(files, is_val, strict=True) if v])
    if not len(xt) or not len(xv):
        raise ValueError(f"need training and validation cubes: {len(xt)} / {len(xv)} frames")
    xt, st = xt.cuda(), st.cuda()  # float16 on the GPU; crops are cast per batch
    n, _, h, w = xt.shape
    model = build_model()
    leak = blind_check(model)
    if leak != 0.0:
        raise AssertionError(f"blind spot leaks: {leak}")
    model = model.cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps,
                                                pct_start=0.05)
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    info = {"n_train_frames": int(n), "n_val_frames": len(xv), "frame_px": [h, w],
            "n_train_pairs": int(n), "valid_px_train": int((xt[:, 1] > 0).sum()),
            "n_params": n_params(model), "steps": steps, "batch": batch, "crop": crop,
            "lr": lr, "val_fields": val_fields,
            "train_files": [f.name for f, v in zip(files, is_val, strict=True) if not v]}
    best = float("inf")
    run = 0.0
    gen = torch.Generator(device="cuda").manual_seed(seed)
    for step in range(1, steps + 1):
        idx = torch.randint(n, (batch,), device="cuda", generator=gen)
        oy = torch.randint(h - crop + 1, (batch,), device="cuda", generator=gen).tolist()
        ox = torch.randint(w - crop + 1, (batch,), device="cuda", generator=gen).tolist()
        xb = torch.stack([xt[i, :, y:y + crop, x:x + crop]
                          for i, y, x in zip(idx.tolist(), oy, ox, strict=True)]).float()
        flips = torch.randint(2, (3,), device="cuda", generator=gen).tolist()
        if flips[0]:
            xb = xb.flip(2)
        if flips[1]:
            xb = xb.flip(3)
        if flips[2]:
            xb = xb.transpose(2, 3)
        g = model(xb, st[idx])
        ok = xb[:, 1] > 0
        loss = huber_loss(g[ok], xb[:, 0][ok], delta=HUBER_DELTA)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        run += float(loss)
        if step % EPOCH_STEPS == 0 or step == steps:
            row = {"step": step, "train_huber": run / EPOCH_STEPS,
                   "seconds": time.time() - t0} | _losses(model, xv, sv)
            run = 0.0
            log.append(row)
            state = {k: v.cpu() for k, v in model.state_dict().items()}
            torch.save(state, out_dir / "last.pt")
            if row["val_huber"] < best:
                best = row["val_huber"]
                torch.save(state, out_dir / "best.pt")
                info["best_step"] = step
            (out_dir / "log.json").write_text(json.dumps(info | {"epochs": log}, indent=1))
            if on_epoch is not None:
                on_epoch()
    return info | {"epochs": log, "gpu_seconds": time.time() - t0}
