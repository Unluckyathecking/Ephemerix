"""Follow-up, after the gate failed on flux: choose the variance used with the model.

    cd tools && uv run python -m denoise.select_variant SELECT_UNIT_DIR

Reads the `select` units (validation fields V01-V04, never the gate fields), in which every
variance choice searched the same injected sources. Rule, fixed before any result was read:

* For each choice, fit forced flux (choice) - forced flux (baseline) = a + b x injected flux
  over all sources, dropping residuals beyond 5 robust sigma. The choice is eligible when
  |a| <= max(2 SE, 1 uJy) and |b| <= max(2 SE, 0.01): it neither adds nor scales flux.
* Among eligible choices take the one with the fewest pooled mirrored-null detections at
  S/N >= 7, then the fewest at >= 6.
* If none is eligible there is no follow-up test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

A_ALLOW_UJY = 1.0
B_ALLOW = 0.01


def flux_fit(f: np.ndarray, diff: np.ndarray) -> dict[str, float]:
    """a, b and their errors for diff = a + b f (uJy), residuals clipped at 5 robust sigma."""
    med = np.median(diff)
    mad = 1.4826 * np.median(np.abs(diff - med))
    keep = np.abs(diff - med) < 5 * mad if mad > 0 else np.ones(diff.shape, bool)
    design = np.stack([np.ones(int(keep.sum())), f[keep]], axis=1)
    coef, *_ = np.linalg.lstsq(design, diff[keep], rcond=None)
    cov = np.linalg.pinv(design.T @ design) * np.var(diff[keep] - design @ coef)
    return {"a_ujy": float(coef[0]), "a_se": float(np.sqrt(cov[0, 0])), "b": float(coef[1]),
            "b_se": float(np.sqrt(cov[1, 1])), "n": int(keep.sum())}


def main(unit_dir: Path) -> dict[str, Any]:
    bases = [json.loads(p.read_text()) for p in sorted(unit_dir.glob("*__base.json"))]
    src = [s for p in sorted(unit_dir.glob("*__inj*.json"))
           for s in json.loads(p.read_text())["sources"]]
    arms = [a for a in bases[0]["arms"] if a != "base"]
    f = 1e3 * np.array([s["flux_mjy"] for s in src])
    out: dict[str, Any] = {"fields": [b["name"] for b in bases], "n_sources": len(src),
                           "choices": {}}
    for arm in ["base", *arms]:
        row: dict[str, Any] = {
            "variance": bases[0]["arms"][arm],
            "null_ge7": sum(d[2] >= 7 for b in bases for d in b[arm]["null"]),
            "null_ge6": sum(d[2] >= 6 for b in bases for d in b[arm]["null"]),
            "null_ge5": sum(d[2] >= 5 for b in bases for d in b[arm]["null"]),
            "real_ge7": sum(d[2] >= 7 for b in bases for d in b[arm]["real"]),
            "recovered_ge7": sum((s[arm]["snr"] or 0) >= 7 for s in src)}
        if arm != "base":
            ok = np.array([s[arm]["forced"] is not None and s["base"]["forced"] is not None
                           for s in src])
            diff = 1e3 * np.array([(s[arm]["forced"] or 0) - (s["base"]["forced"] or 0)
                                   for s in src])
            fit = flux_fit(f[ok], diff[ok])
            row |= fit | {"eligible": bool(
                abs(fit["a_ujy"]) <= max(2 * fit["a_se"], A_ALLOW_UJY)
                and abs(fit["b"]) <= max(2 * fit["b_se"], B_ALLOW))}
        out["choices"][arm] = row
    eligible = [a for a in arms if out["choices"][a]["eligible"]]
    out["chosen"] = min(eligible, key=lambda a: (out["choices"][a]["null_ge7"],
                                                 out["choices"][a]["null_ge6"])) \
        if eligible else None
    out["chosen_variance"] = bases[0]["arms"][out["chosen"]] if out["chosen"] else None
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: select_variant.py SELECT_UNIT_DIR")
    result = main(Path(sys.argv[1]))
    (Path(__file__).resolve().parent / "selection.json").write_text(
        json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
