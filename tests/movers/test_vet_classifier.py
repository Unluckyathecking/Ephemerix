"""The vetting score: deterministic fit, held-out-field gate, model file round trip."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from pxs.movers.classify import load, train
from pxs.movers.train_vet import Samples, run
from pxs.movers.vetdata import FEATURES

I_SHARE = FEATURES.index("max_frame_share")
I_SNR = FEATURES.index("snr")


def _field(name: str, rng: np.random.Generator, informative: bool, n: int = 120) -> Samples:
    """Positives (label 1) at S/N 5-12; negatives (0) at S/N 5-7 plus one at 7.5. When
    informative, negatives are single-frame spikes (max_frame_share high)."""
    lab = np.r_[np.ones(n // 3), np.zeros(n - n // 3)].astype(int)
    snr = np.where(lab == 1, rng.uniform(5, 12, n), rng.uniform(5, 7, n))
    snr[-1] = 7.5
    f = rng.normal(0, 1, (n, len(FEATURES))).astype(np.float32)
    f[:, I_SNR] = snr
    f[:, I_SHARE] = rng.uniform(0.05, 0.3, n)
    if informative:
        f[lab == 0, I_SHARE] = rng.uniform(0.5, 0.9, int((lab == 0).sum()))
    return Samples(np.full(n, name), f, lab, snr)


def _campaign(informative: bool) -> Samples:
    rng = np.random.default_rng(0)
    parts = [_field(f"F{i}", rng, informative) for i in range(6)]
    tno = Samples(np.array(["F5"]), parts[5].feats[:1].copy(), np.array([2]), np.array([20.0]))
    parts.append(tno)
    return Samples(*(np.concatenate([getattr(p, k) for p in parts])
                     for k in ("field", "feats", "label", "snr")))


def test_gate_passes_when_features_separate_artefacts() -> None:
    model, report = run(_campaign(True), {"F4", "F5"})
    m = report["variants"][report["written"]]
    assert m["recall_model"] > m["recall_snr_cut"] + 0.05
    assert m["fp_per_field"] == 1.0  # one negative at S/N 7.5 in each test field
    assert model.gate_passed and m["real_tnos_kept"]
    assert set(report["train_fields"]).isdisjoint(report["test_fields"])


def test_gate_fails_when_features_carry_nothing_beyond_snr() -> None:
    model, report = run(_campaign(False), {"F4", "F5"})
    for m in report["variants"].values():
        assert m["recall_model"] < m["recall_snr_cut"] + 0.05
    assert not model.gate_passed


def test_fit_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    s = _campaign(True)
    a = train(s.feats, (s.label == 1).astype(int), FEATURES, FEATURES, ("x",))
    b = train(s.feats, (s.label == 1).astype(int), FEATURES, FEATURES, ("x",))
    assert a == b
    a.save(tmp_path / "m.json")
    back = load(tmp_path / "m.json")
    assert back is not None
    assert np.allclose(back.score(s.feats, FEATURES), a.score(s.feats, FEATURES))
    assert load(tmp_path / "missing.json") is None


def test_search_output_scores_are_advisory(sky, tmp_path: Path, monkeypatch) -> None:
    from pxs.movers import api, classify
    from pxs.movers.core import run_core
    from pxs.movers.result import LABEL_UNVETTED, Candidate

    d = 50.0
    v = sky.geom.reflex_px_day / d + np.array([0.3, -0.2])
    search, refs = sky.layers(movers=[(40.0, 38.0, d, float(v[0]), float(v[1]), 0.06)])
    core = run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec)
    cand = Candidate(1, LABEL_UNVETTED, 0, 0, 0, 0, 0, (0, 0), 9, 9, 5, 5, 1, 1, {}, 0.0)
    monkeypatch.setattr(classify, "MODEL_PATH", tmp_path / "none.json")
    same, info = api._vet_scores(core, [cand])
    assert info is None and same[0].vet_score is None
    s = _campaign(True)
    train(s.feats, (s.label == 1).astype(int), FEATURES, FEATURES, ("x",)).save(
        tmp_path / "none.json")
    scored, info = api._vet_scores(core, [cand])
    assert info is not None and info["gate_passed"] is False
    assert 0.0 <= scored[0].vet_score <= 1.0 and scored[0].label == LABEL_UNVETTED


def test_gate_fails_without_test_negatives() -> None:
    s = _campaign(True)
    keep = ~(np.isin(s.field, ["F4", "F5"]) & (s.label == 0))
    _, report = run(Samples(s.field[keep], s.feats[keep], s.label[keep], s.snr[keep]),
                    {"F4", "F5"})
    assert not any(m["gate_passed"] for m in report["variants"].values())


def test_failed_model_is_not_written_where_the_search_loads_it(tmp_path: Path) -> None:
    from pxs.movers import train_vet

    camp = tmp_path / "camp"
    camp.mkdir()
    s = _campaign(False)
    for name in sorted(set(s.field.tolist())):
        m = s.field == name
        np.savez(camp / f"{name}.npz", F=s.feats[m], Y=s.label[m], S=s.snr[m])
    out, failed = tmp_path / "vet_model.json", tmp_path / "failed.json"
    train_vet.main(["--campaign", str(camp), "--test", "F4,F5", "--out", str(out),
                    "--failed", str(failed), "--report", str(tmp_path / "r.json")])
    assert failed.exists() and not out.exists()
