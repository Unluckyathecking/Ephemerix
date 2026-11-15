"""Train and gate the vetting score on campaign samples (deploy/modal_movers.py writes them).

    python -m pxs.movers.train_vet --campaign cache/movers/campaign \
        --test Haumea,Eris,B6,B7 [--out src/pxs/movers/vet_model.json]

Each <field>.npz holds samples: F (features, vetdata.FEATURES), Y (1 = recovered injection,
0 = real-sky or mirrored-null detection with nothing injected, 2 = catalogued TNO, never
trained on), S (clipped S/N), R (source). Training and test fields are disjoint.

Operating point: the plain S/N >= 7 cut gives some false positives per test field. The model's
threshold is set to give no more on the same test negatives; the gate passes only if the model
then keeps a larger share of test positives (by GATE_MIN_GAIN) and keeps every real TNO.
Both models, with and without the S/N feature, are evaluated. The better one is written to
--out (the committed model the search loads) only if it passed the gate; otherwise to
--failed, so an unvalidated model never reaches result.json.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from .classify import MODEL_PATH, VetModel, train
from .core import THRESHOLD
from .vetdata import FEATURES

log = logging.getLogger(__name__)

GATE_MIN_GAIN = 0.05  # absolute gain in held-out positive recall at equal false positives


@dataclass(frozen=True)
class Samples:
    field: np.ndarray
    feats: np.ndarray
    label: np.ndarray
    snr: np.ndarray

    def where(self, m: np.ndarray) -> Samples:
        return Samples(self.field[m], self.feats[m], self.label[m], self.snr[m])


def load_campaign(directory: Path) -> Samples:
    """All samples of every <field>.npz in `directory` (files starting test_ are skipped)."""
    parts = []
    for p in sorted(directory.glob("*.npz")):
        if p.stem.startswith("test_"):
            continue
        z = np.load(p)
        if len(z["Y"]):
            parts.append(Samples(np.full(len(z["Y"]), p.stem), z["F"], z["Y"], z["S"]))
    if not parts:
        raise ValueError(f"no campaign samples in {directory}")
    return Samples(*(np.concatenate([getattr(s, k) for s in parts])
                     for k in ("field", "feats", "label", "snr")))


def evaluate(scores: np.ndarray, test: Samples) -> dict[str, Any]:
    """Recall of positives for the S/N cut and for the model at no more false positives."""
    pos, neg, tno = test.label == 1, test.label == 0, test.label == 2
    n_fields = max(len(set(test.field.tolist())), 1)
    k = int(np.sum(test.snr[neg] >= THRESHOLD))
    neg_sorted = np.sort(scores[neg])[::-1]
    thr = float(np.nextafter(neg_sorted[k], 1.0)) if k < neg_sorted.size else 0.0
    band = pos & (test.snr < THRESHOLD)
    return {
        "n_test_fields": n_fields, "n_pos": int(pos.sum()), "n_neg": int(neg.sum()),
        "fp_per_field": k / n_fields, "threshold": thr,
        "recall_snr_cut": float(np.mean(test.snr[pos] >= THRESHOLD)) if pos.any() else None,
        "recall_model": float(np.mean(scores[pos] >= thr)) if pos.any() else None,
        "recall_model_below_cut": float(np.mean(scores[band] >= thr)) if band.any() else None,
        "real_tno_scores": [round(float(s), 4) for s in scores[tno]],
        "real_tnos_kept": bool(np.all(scores[tno] >= thr)),
    }


def gate(m: dict[str, Any]) -> bool:
    if m["recall_model"] is None or m["recall_snr_cut"] is None or m["n_neg"] == 0:
        return False  # without held-out negatives the threshold is vacuous
    return m["real_tnos_kept"] and m["recall_model"] >= m["recall_snr_cut"] + GATE_MIN_GAIN


def run(samples: Samples, test_fields: set[str]) -> tuple[VetModel, dict[str, Any]]:
    """Train on non-test fields (labels 0/1), evaluate on test fields; best variant + report."""
    is_test = np.isin(samples.field, sorted(test_fields))
    tr = samples.where(~is_test & (samples.label != 2))
    te = samples.where(is_test)
    if not tr.label.size or not te.label.size or len(set(tr.label.tolist())) < 2:
        raise ValueError("need both classes in training fields and samples in test fields")
    report: dict[str, Any] = {"train_fields": sorted(set(tr.field.tolist())),
                              "test_fields": sorted(set(te.field.tolist())),
                              "n_train": int(tr.label.size), "variants": {}}
    best: tuple[VetModel, dict[str, Any]] | None = None
    for name, use in (("all_features", FEATURES),
                      ("without_snr", tuple(f for f in FEATURES if f != "snr"))):
        model = train(tr.feats, tr.label, FEATURES, use, tuple(report["train_fields"]))
        m = evaluate(model.score(te.feats, FEATURES), te)
        m["gate_passed"] = gate(m)
        report["variants"][name] = m
        if best is None or (m["recall_model"] or 0) > (best[1]["recall_model"] or 0):
            best = (replace(model, gate_passed=m["gate_passed"], metrics={name: m}), m)
    assert best is not None
    report["written"] = next(iter(best[0].metrics))
    return best[0], report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.movers.train_vet")
    ap.add_argument("--campaign", type=Path, default=Path("cache/movers/campaign"))
    ap.add_argument("--test", required=True, help="comma-separated held-out field names")
    ap.add_argument("--out", type=Path, default=MODEL_PATH)
    ap.add_argument("--failed", type=Path, default=Path("cache/movers/vet_model_failed.json"))
    ap.add_argument("--report", type=Path, default=Path("cache/movers/vet_report.json"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    model, report = run(load_campaign(args.campaign), set(args.test.split(",")))
    dest = args.out if model.gate_passed else args.failed
    dest.parent.mkdir(parents=True, exist_ok=True)
    model.save(dest)
    report["model_file"] = str(dest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
