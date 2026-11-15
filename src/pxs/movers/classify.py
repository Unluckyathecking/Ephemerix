"""Candidate vetting score: L2-regularised logistic regression on vetdata.FEATURES (numpy and
scipy only; no new dependency). Trained by `python -m pxs.movers.train_vet`.

The score is advisory. It never changes a candidate's label or drops one; the model file
records whether it passed the held-out-field gate, and the
search reports that next to every score.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

MODEL_PATH = Path(__file__).with_name("vet_model.json")
L2 = 1.0


@dataclass(frozen=True)
class VetModel:
    """Standardised-feature logistic regression. `features` names the columns used, in
    order, from vetdata.FEATURES. gate_passed: beat the S/N cut on held-out fields."""

    features: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    gate_passed: bool
    trained_on: tuple[str, ...]
    metrics: dict[str, Any] = field(default_factory=dict)

    def score(self, feats: np.ndarray, names: tuple[str, ...]) -> np.ndarray:
        """P(real mover) for rows of `feats`, whose columns are named by `names`."""
        cols = [names.index(f) for f in self.features]
        x = (np.atleast_2d(feats)[:, cols] - np.array(self.mean)) / np.array(self.scale)
        return 1.0 / (1.0 + np.exp(-(x @ np.array(self.coef) + self.intercept)))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1) + "\n")


def load(path: Path | None = None) -> VetModel | None:
    """The model at `path` (default: the committed MODEL_PATH), or None if there is none."""
    path = MODEL_PATH if path is None else path
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    return VetModel(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})


def fit(x: np.ndarray, y: np.ndarray, l2: float = L2) -> tuple[np.ndarray, float]:
    """(coef, intercept) minimising class-balanced log-loss + l2/2 |coef|^2 on standardised x.
    Deterministic: L-BFGS from zeros."""
    y = y.astype(float)
    n_pos, n_neg = max(y.sum(), 1.0), max((1 - y).sum(), 1.0)
    w = np.where(y > 0, 0.5 / n_pos, 0.5 / n_neg)

    def loss(p: np.ndarray) -> tuple[float, np.ndarray]:
        z = x @ p[:-1] + p[-1]
        # log(1 + e^z) - y z, written stably
        ll = np.logaddexp(0.0, z) - y * z
        g = w * (1.0 / (1.0 + np.exp(-z)) - y)
        val = float(np.sum(w * ll) + 0.5 * l2 * np.sum(p[:-1] ** 2) / len(y))
        grad = np.concatenate([x.T @ g + l2 * p[:-1] / len(y), [g.sum()]])
        return val, grad

    res = minimize(loss, np.zeros(x.shape[1] + 1), jac=True, method="L-BFGS-B")
    return res.x[:-1], float(res.x[-1])


def train(feats: np.ndarray, y: np.ndarray, names: tuple[str, ...], use: tuple[str, ...],
          trained_on: tuple[str, ...]) -> VetModel:
    """Fit on the columns `use` of `feats` (labels 1 = real mover, 0 = not)."""
    cols = [names.index(f) for f in use]
    x = feats[:, cols].astype(float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    coef, b = fit((x - mean) / scale, y)
    return VetModel(use, tuple(mean.tolist()), tuple(scale.tolist()), tuple(coef.tolist()), b,
                    False, trained_on)
