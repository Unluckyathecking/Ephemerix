"""Basic contract of pxs.typing.match_spectrum. Rules are tested in test_typing_rules.py,
the pair test in test_typing_pairs.py and real spectra in test_typing_real.py."""

import numpy as np
import pytest

from pxs.typing import FEATURES, blackbody, load_templates, match_spectrum
from pxs.typing.models import bb_fnu

TOP_KEYS = {"best", "runner_up", "delta_chi2", "verdict", "confidence", "candidates", "models",
            "method", "class", "type_range", "delta_class", "range_open_warm",
            "range_open_cold", "pair", "bands_detected", "detection_sigma"}
CLASSES = {"brown dwarf", "star", "not a brown dwarf", "uncertain"}


def shape(label):
    """F_nu shape of a template (on its own grid) or of "star (T K)" (a blackbody)."""
    t = load_templates()
    wl = next(iter(t.values())).wl_um
    if label.startswith("star"):
        return wl, bb_fnu(wl, float(label.split("(")[1].split()[0]), 0.0)
    return wl, t[label].flam * wl**2


def synth(label, noise=0.0, seed=0, step=1, mean_mjy=2.0):
    """Spectrum on the SPHEREx template grid: (wl, flux_mjy, err_mjy).

    noise=0 gives a noiseless spectrum with 2% errors; otherwise 10% Gaussian noise.
    """
    wl, f = shape(label)
    wl, f = wl[::step], f[::step]
    f = f * mean_mjy / f.mean()
    if not noise:
        return wl, f, 0.02 * f
    err = 0.1 * f
    rng = np.random.default_rng(seed)
    return wl, f + rng.normal(0, 1, f.size) * err, err


def subtype(label):
    return int(label[1]) + 10 * "MLTY".index(label[0])


def test_templates_ordered_m_to_y():
    keys = list(load_templates())
    assert keys[0] == "M8" and keys[-1] == "Y1" and len(keys) == 24
    assert keys.index("L9") < keys.index("T0") < keys.index("Y0")


def test_blackbody_is_planck():
    wl = np.array([1.0, 2.0, 4.0])
    f = blackbody(wl, 3000)
    assert f[1] == pytest.approx(1.0)
    assert f[0] > f[1] > f[2]
    # Wien's law: F_lambda peaks at 2898 um K / T, i.e. 0.966 um at 3000 K
    grid = np.linspace(0.5, 2, 3000)
    assert grid[np.argmax(blackbody(grid, 3000))] == pytest.approx(2898 / 3000, abs=0.01)


@pytest.mark.parametrize("label", list(load_templates()))
def test_each_template_typed_as_itself(label):
    r = match_spectrum(*synth(label))
    assert r["best"]["type"] == label


def test_output_keys_match_api():
    r = match_spectrum(*synth("T8", noise=1, seed=1))
    assert set(r) == TOP_KEYS
    assert set(r["best"]) == {"type", "chi2", "dof"}
    assert set(r["runner_up"]) == {"type", "chi2", "dof"}
    assert r["confidence"] in {"high", "medium", "low"}
    assert isinstance(r["verdict"], str) and r["verdict"].endswith(".")
    # candidates: the 24 templates plus the best star, dust, power law and star + dust,
    # sorted by the penalised score (was: 24 templates and 3 stars sorted by chi2)
    scores = [c["score"] for c in r["candidates"]]
    assert scores == sorted(scores)
    assert len(r["candidates"]) == 24 + 4
    assert {c["family"] for c in r["candidates"]} == {"brown dwarf", "star", "dust", "power law",
                                                      "star + dust"}
    assert r["candidates"][0]["type"] == r["best"]["type"]
    assert set(r["models"]) == {r["best"]["type"], r["runner_up"]["type"]}
    assert r["delta_chi2"] == pytest.approx(scores[1] - scores[0], abs=0.02)
    assert r["class"] in CLASSES
    assert isinstance(r["delta_class"], float) and r["delta_class"] >= 0
    assert isinstance(r["range_open_warm"], bool) and isinstance(r["range_open_cold"], bool)
    assert r["pair"] is None or set(r["pair"]) == {"types", "chi2", "delta_vs_single"}
    assert all(isinstance(b, str) for b in r["bands_detected"])
    # 90 points, 5 dropped, two free parameters (type and scale) for a template
    assert r["best"]["dof"] == 90 - 5 - 2
    assert all(len(p) == 2 for p in r["models"][r["best"]["type"]])


def test_noisy_t8_recovered_within_one_subtype():
    errs = []
    for seed in range(40):
        r = match_spectrum(*synth("T8", noise=1, seed=seed))
        errs.append(abs(subtype(r["best"]["type"]) - subtype("T8")))
    assert max(errs) <= 1
    assert np.mean(np.array(errs) == 0) >= 0.5


def test_models_scaled_to_data_in_mjy():
    wl, f, e = synth("T8", noise=1, seed=3, mean_mjy=2.0)
    r = match_spectrum(wl, f, e)
    model = np.array(r["models"][r["best"]["type"]])
    assert model[:, 1].mean() == pytest.approx(f.mean(), rel=0.1)


def test_star_model_scaled_to_data_in_mjy():
    wl, f, e = synth("star (4500 K)", noise=1, seed=3, mean_mjy=5.0)
    r = match_spectrum(wl, f, e)
    model = np.array(r["models"][r["best"]["type"]])
    assert np.interp(wl, model[:, 0], model[:, 1]).mean() == pytest.approx(f.mean(), rel=0.05)


def test_blackbody_called_star():
    for seed in range(10):
        r = match_spectrum(*synth("star (4500 K)", noise=1, seed=seed))
        assert r["best"]["type"].startswith("star")
        assert r["class"] == "star" and r["type_range"] is None
        assert r["confidence"] != "low"
        assert r["verdict"] == "Looks like an ordinary star, not a brown dwarf."


def test_sparse_sampling_still_works():
    r = match_spectrum(*synth("T8", noise=1, seed=4, step=4))
    assert r is not None
    assert abs(subtype(r["best"]["type"]) - subtype("T8")) <= 1
    assert r["best"]["dof"] == 23 - 2  # fewer than 25 points: nothing dropped


def test_flagged_and_nan_points_ignored():
    wl, f, e = synth("T8", noise=1, seed=5)
    flagged = np.zeros(wl.size, bool)
    flagged[10:20] = True
    f2, e2 = f.copy(), e.copy()
    f2[10:20] = 1e6  # garbage under the flags must not matter
    f2[40], e2[50] = np.nan, np.nan
    base_mask = np.isin(np.arange(wl.size), [*range(10, 20), 40, 50])
    base = match_spectrum(wl, f, e, flagged=base_mask)
    got = match_spectrum(wl, f2, e2, flagged=flagged)
    assert got["best"] == base["best"]
    assert got["delta_chi2"] == base["delta_chi2"]


def test_inputs_not_mutated():
    wl, f, e = synth("T8", noise=1, seed=6)
    f[3] = np.nan
    before = (wl.copy(), f.copy(), e.copy())
    match_spectrum(wl, f, e)
    for a, b in zip((wl, f, e), before):
        np.testing.assert_array_equal(a, b)


def test_unsorted_input_gives_same_answer():
    wl, f, e = synth("T6", noise=1, seed=6)
    order = np.random.default_rng(0).permutation(wl.size)
    a, b = match_spectrum(wl[order], f[order], e[order]), match_spectrum(wl, f, e)
    for key in ("class", "type_range", "verdict", "confidence", "pair"):
        assert a[key] == b[key]
    assert a["best"]["type"] == b["best"]["type"]


def test_too_few_points_returns_none():
    wl, f, e = synth("T8", noise=1)
    assert match_spectrum(wl[:7], f[:7], e[:7]) is None
    flagged = np.ones(wl.size, bool)
    flagged[:7] = False
    assert match_spectrum(wl, f, e, flagged=flagged) is None
    assert match_spectrum(wl[:8], f[:8], e[:8]) is not None


def test_points_outside_template_range_ignored():
    wl, f, e = synth("T8", noise=1, seed=7)
    wl2 = np.concatenate([[0.8, 0.9], wl, [5.2]])
    f2 = np.concatenate([[9.0, 9.0], f, [9.0]])
    e2 = np.concatenate([[0.1, 0.1], e, [0.1]])
    assert match_spectrum(wl2, f2, e2)["best"] == match_spectrum(wl, f, e)["best"]


def test_few_clean_points_is_low_confidence_and_uncertain():
    wl, f, e = synth("T8", noise=1, seed=8, step=9)  # 10 points
    r = match_spectrum(wl, f, e)
    assert r["confidence"] == "low" and r["class"] == "uncertain"
    assert r["verdict"] == "Too few clean measurements to classify."


def test_clean_t8_verdict_names_type_range():
    # The range is never narrower than one subtype either side (was "type T8").
    r = match_spectrum(*synth("T8"))
    assert r["best"]["type"] == "T8"
    assert r["class"] == "brown dwarf" and r["confidence"] == "high"
    assert r["verdict"] == "Consistent with a cold brown dwarf, type T7 to T9 (best match T8)."
    assert r["type_range"] == ["T7", "T9"]
    assert "CH4 3.3 um" in r["bands_detected"]


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        match_spectrum([1.0, 2.0], [1.0], [0.1, 0.1])


def test_features_shape():
    labels = [f["label"] for f in FEATURES]
    assert {"H2O", "CH4", "CO", "CO2"} <= set(labels)
    assert all(len(f["wl_um"]) == 2 and f["wl_um"][0] < f["wl_um"][1] for f in FEATURES)


def test_noisy_t8_is_confident_brown_dwarf_with_honest_range():
    for seed in range(40):
        r = match_spectrum(*synth("T8", noise=1, seed=seed))
        assert r["class"] == "brown dwarf" and r["confidence"] == "high"
        lo, hi = r["type_range"]
        assert subtype(lo) <= subtype(r["best"]["type"]) - 1
        assert subtype(hi) >= subtype(r["best"]["type"]) + 1
        assert subtype(hi) - subtype(lo) + 1 <= 5
