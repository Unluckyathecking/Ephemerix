"""Stage 3: does a learned filter beat a plain S/N cut on held-out fields?

Run (optional dependencies only here, never in the package):
    uv run --with scikit-learn --with torch python probes/movers/vet_models.py

Training fields and test fields are disjoint. Positives: injected movers detected at seed
S/N >= 5. Negatives: real-sky and mirrored-null detections at seed S/N >= 5 (no injection).
The operating point is the completeness of the plain S/N >= 7 cut on the test positives;
each model's score threshold is set to keep the same share of test positives, and its
false positives per field (real-sky negatives above threshold) are compared. Gate 3: ship
only if the CNN at least halves them and keeps all three real TNOs (label 2).
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from torch import nn

SEED = 7
TEST = {"Haumea", "Makemake", "Eris", "B6", "B7"}
CAMPAIGN = Path("cache/movers/campaign")
torch.manual_seed(SEED)
rng = np.random.default_rng(SEED)


def load():
    rows = []
    for p in sorted(CAMPAIGN.glob("*.npz")):
        if p.stem.startswith("test_"):
            continue
        z = np.load(p)
        for i in range(len(z["Y"])):
            rows.append((p.stem, z["X"][i], z["F"][i], int(z["Y"][i]), float(z["S"][i]),
                         str(z["R"][i])))
    return rows


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.f = nn.Sequential(
            nn.Conv2d(4, 16, 3, padding=1), nn.ReLU(), nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
            nn.MaxPool2d(2), nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        return self.f(x).squeeze(1)


def prep(x: np.ndarray) -> np.ndarray:
    return np.clip(np.nan_to_num(x), -20, 20) / 5.0


def train_cnn(x: np.ndarray, y: np.ndarray) -> Net:
    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    pos_w = torch.tensor(max((y == 0).sum(), 1) / max((y == 1).sum(), 1), dtype=torch.float32)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    xt, yt = torch.tensor(prep(x), dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    for _ in range(30):
        perm = torch.randperm(len(yt))
        for b in range(0, len(yt), 64):
            idx = perm[b:b + 64]
            xb = xt[idx]
            k = int(rng.integers(4))
            xb = torch.rot90(xb, k, (2, 3))
            if rng.uniform() < 0.5:
                xb = torch.flip(xb, (3,))
            opt.zero_grad()
            lossf(net(xb), yt[idx]).backward()
            opt.step()
    return net


def score_cnn(net: Net, x: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return torch.sigmoid(net(torch.tensor(prep(x), dtype=torch.float32))).numpy()


def operating(score, pos, neg_real, n_fields, keep):
    """Threshold keeping `keep` share of positives; real negatives above it per field."""
    thr = np.quantile(score[pos], 1 - keep) if pos.any() else np.inf
    return float(thr), float((score[neg_real] >= thr).sum()) / n_fields


def main() -> int:
    rows = load()
    if not rows:
        print("no campaign data")
        return 1
    field = np.array([r[0] for r in rows])
    X = np.stack([r[1] for r in rows])
    F = np.stack([r[2] for r in rows])
    Y = np.array([r[3] for r in rows])
    S = np.array([r[4] for r in rows])
    R = np.array([r[5] for r in rows])
    test = np.isin(field, list(TEST))
    tr = ~test & (Y != 2)
    te = test & (Y != 2)
    n_test_fields = len(set(field[test]))
    pos, negr = te & (Y == 1), te & (Y == 0) & (R == "real")
    negn = te & (Y == 0) & (R == "null")
    keep = float((S[pos] >= 7).mean())
    out = {"n_train": int(tr.sum()), "n_train_pos": int((tr & (Y == 1)).sum()),
           "n_test_pos": int(pos.sum()), "n_test_neg_real": int(negr.sum()),
           "n_test_neg_null": int(negn.sum()), "test_fields": sorted(set(field[test])),
           "train_fields": sorted(set(field[~test])), "completeness_at_snr7": keep}
    fp_snr = float((S[negr] >= 7).sum()) / n_test_fields
    fp_snr_null = float((S[negn] >= 7).sum()) / n_test_fields
    sc = StandardScaler().fit(F[tr])
    lr = LogisticRegression(max_iter=2000, class_weight="balanced").fit(sc.transform(F[tr]), Y[tr])
    s_lr = lr.predict_proba(sc.transform(F))[:, 1]
    net = train_cnn(X[tr], Y[tr])
    s_cnn = score_cnn(net, X)
    res = {"snr7": {"fp_real_per_field": fp_snr, "fp_null_per_field": fp_snr_null}}
    for name, s in (("logreg", s_lr), ("cnn", s_cnn)):
        thr, fp = operating(s, pos, negr, n_test_fields, keep)
        res[name] = {"threshold": thr, "fp_real_per_field": fp,
                     "fp_null_per_field": float((s[negn] >= thr).sum()) / n_test_fields,
                     "real_tnos": {f: round(float(s[i]), 3) for i, f in
                                   zip(np.flatnonzero(Y == 2), field[Y == 2])},
                     "real_tnos_kept": bool(np.all(s[Y == 2] >= thr))}
    out["results"] = res
    out["cnn_params"] = sum(p.numel() for p in net.parameters())
    fp_cnn = res["cnn"]["fp_real_per_field"] + res["cnn"]["fp_null_per_field"]
    fp_base = fp_snr + fp_snr_null
    out["gate3_pass"] = bool(res["cnn"]["real_tnos_kept"] and fp_base > 0
                             and fp_cnn <= 0.5 * fp_base)
    Path("cache/movers/vet_models.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
