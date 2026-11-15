"""Glare, crowding and the motion gate (`pxs.fieldcheck`), with a replay of the gallery's
published motions: the gate and the glare cut in `motion_frames` change none of them."""

import json
from pathlib import Path

import numpy as np
import pytest

from pxs import fieldcheck
from pxs.grid import Grid, Stack
from pxs.manifest import measured_motion, motion_frames

GALLERY = Path(__file__).resolve().parents[1] / "web" / "gallery"
VIEWS = sorted(p.parent.name for p in GALLERY.glob("*/manifest.json"))


def _frame(mission: str, near: float | None, **kw) -> dict:
    return {"mission": mission, "no_data_near_target": near, "centroid_px": None,
            "flag_fraction": 0.0, **kw}


def test_frame_gaps_near_and_overall():
    img = np.ones((100, 100), np.float32)
    mask = np.zeros((100, 100), bool)
    mask[40:60, 40:60] = True
    st = Stack(image=img, mission="WISE", band="W2", wavelength_um=(4.0, 5.2), mjd=58000.0,
               date_span_days=1.0, n_exposures=10, native_pixscale_arcsec=2.75,
               saturated_mask=mask)
    g = fieldcheck.frame_gaps(st, (50.0, 50.0), 1.0)
    assert g["no_data_fraction"] == 0.04
    assert g["no_data_near_target"] == pytest.approx(400 / (np.pi * 30**2), abs=0.01)
    assert fieldcheck.frame_gaps(st, (150.0, 50.0), 1.0)["no_data_near_target"] is None


def test_betelgeuse_like_glare_in_both_missions():
    frames = [_frame("WISE", 1.0)] * 5 + [_frame("SPHEREx", 1.0)] * 4 + [_frame("SPHEREx", 0.0)]
    f = fieldcheck.field(frames, None)
    assert f["saturated"] and f["saturated_missions"] == ["SPHEREx", "WISE"]
    assert f["crowded"] is None and f["crowding"] is None
    (s,) = fieldcheck.sentences(f)
    assert s.startswith("This spot is so bright in the infrared that it overloads both WISE and SPHEREx")
    assert "—" not in s


@pytest.mark.parametrize(("wise", "spherex"), [(0.12, 0.28), (0.48, 0.81), (0.04, 0.01)])
def test_saturated_gallery_stars_are_not_glare(wise, spherex):
    """Barnard's Star, R Draconis and RW Aurigae, rebuilt: medians of their frames."""
    frames = [_frame("WISE", wise)] * 5 + [_frame("SPHEREx", spherex)] * 5
    f = fieldcheck.field(frames, [])
    assert not f["saturated"] and f["saturated_missions"] == [] and fieldcheck.sentences(f) == []


def test_glare_in_wise_only():
    f = fieldcheck.field([_frame("WISE", 1.0)] * 3 + [_frame("SPHEREx", 0.2)] * 3, None)
    assert f["saturated_missions"] == ["WISE"]
    assert "it overloads WISE:" in fieldcheck.sentences(f)[0]


def test_glare_from_spherex_alone_when_there_is_no_wise_frame():
    """Betelgeuse with the WISE images not loaded: every SPHEREx band is glare."""
    bands = [f"spx-b{i}" for i in range(1, 7)]
    frames = [_frame("SPHEREx", 1.0, band=b) for b in bands for _ in range(3)]
    f = fieldcheck.field(frames, None)
    assert f["saturated"] and f["saturated_missions"] == ["SPHEREx"]
    (s,) = fieldcheck.sentences(f)
    assert s.startswith("This spot is so bright in the infrared that it overloads SPHEREx: ")
    assert "WISE" not in s


def test_spherex_alone_needs_most_bands_in_glare():
    def view(glared: int) -> list[dict]:
        return [_frame("SPHEREx", 1.0 if i < glared else 0.1, band=f"spx-b{i + 1}")
                for i in range(6) for _ in range(2)]
    assert not fieldcheck.field(view(3), None)["saturated"]  # half the bands is not most
    assert fieldcheck.field(view(4), None)["saturated_missions"] == ["SPHEREx"]
    assert not fieldcheck.field([], None)["saturated"]
    # With a WISE frame in the view, WISE still decides (R Draconis: a star with a core).
    with_wise = [*view(6), _frame("WISE", 0.48, band="W2")]
    assert not fieldcheck.field(with_wise, None)["saturated"]


def test_motion_not_measured_names_the_missing_wise_images():
    det = [_frame("SPHEREx", 1.0, centroid_px=[1.0, 1.0], flag_fraction=0.66, band="spx-b6")]
    f = fieldcheck.field(det, None)
    for frames in ([], det):  # with or without a SPHEREx detection
        motion, nm = fieldcheck.gate_motion(None, f, frames, wise_missing=True)
        assert motion is None and nm["reason"] == fieldcheck.NO_WISE_REASON
        assert (nm["n_detections"], nm["baseline_years"]) == (0, 0.0)
    thin = {"pmra_masyr": 1.0, "pmdec_masyr": 1.0, "n_detections": 9, "baseline_years": 1.2}
    assert fieldcheck.gate_motion(thin, f, det, wise_missing=True)[1] == {
        "reason": fieldcheck.NO_WISE_REASON, "n_detections": 9, "baseline_years": 1.2}
    long = {**thin, "baseline_years": 14.0}  # a motion that stands is still published
    assert fieldcheck.gate_motion(long, f, det, wise_missing=True) == (long, None)


def test_apply_blames_wise_only_when_it_failed_and_gave_no_frame():
    spx = [_frame("SPHEREx", 1.0, band="spx-b6", centroid_px=[1.0, 1.0], flag_fraction=0.7)]
    m = {"frames": spx, "measured_motion": None,
         "warnings": ["WISE images could not be loaded; the archive did not answer."]}
    out = fieldcheck.apply(m, None, wise_failed=True)
    glare = ("This spot is so bright in the infrared that it overloads SPHEREx: most of the "
             "images show glare and detector artefacts rather than the object itself, and the "
             "flat patches in them are where there is no usable measurement.")
    motion = ("Motion not measured: the WISE images could not be loaded; a motion needs their "
              "years of positions.")
    assert out["warnings"][:2] == [glare, motion]
    assert len(out["warnings"]) == len(set(out["warnings"])) == 3
    # WISE failed in part but gave frames: the usual rules, not the missing-WISE reason.
    part = {**m, "frames": [*spx, _frame("WISE", 1.0, band="W2")]}
    nm = fieldcheck.apply(part, None, wise_failed=True)["motion_not_measured"]
    assert nm["reason"] == "every detection is in an image that is mostly glare or gaps"
    # No failure (WISE simply has nothing here): nothing is said about the motion.
    quiet = {**m, "frames": [_frame("SPHEREx", 0.0, band="spx-b6")]}
    assert fieldcheck.apply(quiet, None)["motion_not_measured"] is None


def test_crowding_from_a_full_catalogue_list():
    bright = [{"w2_mag": 9.0 + i * 0.03} for i in range(130)]
    faint = [{"w2_mag": 12.0 + i * 0.03} for i in range(130)]
    assert fieldcheck.crowding(bright)["crowded"] is True
    assert fieldcheck.crowding(faint)["crowded"] is False  # reaches W2 15.9
    assert fieldcheck.crowding(bright[:20])["crowded"] is False  # a short list is not crowding
    f = fieldcheck.field([], bright)
    assert fieldcheck.sentences(f)[0].startswith("This field is too crowded to follow one object")


@pytest.mark.parametrize(("n", "base"), [(2, 1.0), (3, 1.01), (10, 1.5)])
def test_thin_motion_is_not_measured(n, base):
    mm = {"pmra_masyr": 102.2, "pmdec_masyr": 149.3, "err_masyr": 561.1, "n_detections": n,
          "baseline_years": base}
    shown, nm = fieldcheck.gate_motion(mm, fieldcheck.field([], None))
    assert shown is None and nm["n_detections"] == n
    assert fieldcheck.not_measured_sentence(nm).startswith(f"Motion not measured: only {n} clean")


def test_all_frames_fit_in_glare_and_glare_only_detections():
    mm = {"pmra_masyr": 1.0, "pmdec_masyr": 1.0, "method": "all_frames", "n_frames": 40,
          "n_detections": 0, "baseline_years": 14.0}
    glare = fieldcheck.field([_frame("WISE", 1.0)], None)
    assert fieldcheck.gate_motion(mm, glare)[0] is None
    assert fieldcheck.gate_motion(mm, fieldcheck.field([], None))[0] == mm
    det = [_frame("SPHEREx", 1.0, centroid_px=[1.0, 1.0], flag_fraction=0.66)]
    _, nm = fieldcheck.gate_motion(None, glare, det)
    assert nm["reason"] == "every detection is in an image that is mostly glare or gaps"
    assert fieldcheck.gate_motion(None, glare, [])[1] is None
    clean = [*det, _frame("WISE", 0.0, centroid_px=[2.0, 2.0])]  # a faint target seen once
    assert fieldcheck.gate_motion(None, glare, clean) == (None, None)


def test_apply_puts_the_field_sentences_first():
    m = {"frames": [_frame("WISE", 1.0)], "warnings": ["Older note."],
         "measured_motion": {"pmra_masyr": 1.0, "pmdec_masyr": 1.0, "n_detections": 2,
                             "baseline_years": 1.0}}
    out = fieldcheck.apply(m, None)
    assert out["measured_motion"] is None and out["motion_not_measured"]["n_detections"] == 2
    assert out["warnings"][0].startswith("This spot is so bright")
    assert out["warnings"][1].startswith("Motion not measured")
    assert out["warnings"][2] == "Older note." and m["warnings"] == ["Older note."]


@pytest.mark.parametrize("slug", VIEWS)
def test_gallery_motions_are_unchanged(slug):
    m = json.loads((GALLERY / slug / "manifest.json").read_text())
    pub = m.get("measured_motion")
    out = fieldcheck.apply(m, m["overlays"].get("catwise"))
    assert not out["field"]["saturated"] and not out["field"]["crowded"]
    assert out["measured_motion"] == pub and out["motion_not_measured"] is None
    assert out["warnings"] == m["warnings"]  # nothing new for a visitor to read
    if pub is None or pub.get("method") == "all_frames" or "solar_system" in m:
        return
    grid = Grid(m["center"]["ra"], m["center"]["dec"], m["fov_arcsec"], m["size_px"])
    plx = pub["parallax_mas"] if pub["parallax_model"] == "fixed" else None
    assert all(fr["flag_fraction"] < fieldcheck.GLARE_FLAG_FRACTION for fr in motion_frames(m["frames"]))
    again = measured_motion(m["frames"], grid, plx)
    for k in ("pmra_masyr", "pmdec_masyr", "err_masyr", "n_detections", "baseline_years"):
        assert again[k] == pytest.approx(pub[k], abs=0.02), k
