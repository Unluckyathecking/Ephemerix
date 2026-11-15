"""Re-measure the motion of built views offline and print it before and after.

    uv run python probes/astro/dump_stacks.py <slug> [...]        (once: real WISE stacks)
    uv run python probes/astro/refresh_motion.py <out dir> [slug ...]

For each slug (default: every view in web/gallery that has cache/astro/<slug>.pkl) the WISE
frames are measured again with the current code on the real stacks, using the Gaia and
CatWISE lists stored in the published manifest, so no catalogue service is needed. SPHEREx
frames are taken from the published manifest as they are. The refreshed manifest is written
to <out dir>/<slug>/manifest.json (never into web/gallery), with <out dir>/validation.json
built from the refreshed and the untouched published manifests. A WISE frame "changed" when
its centroid differs from the published one although it was not fitted with a neighbour:
that should be 0, and says the replay reproduces the published build.

With --joint-after-star-removal the joint fit with neighbours is also used on frames where
a catalogued star was subtracted first: the variant that was tried and left out, because
it returns the blended frames of CWISE J2112-0529 and its declination motion then differs
from the catalogue by 3.8 sigma (9 frames) instead of 1.5 (5 frames):

    uv run python probes/astro/refresh_motion.py /tmp/x cwise-2112-0529 --joint-after-star-removal

Written with Claude Code.
"""

from __future__ import annotations

import json
import pickle
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pxs import blend, centroid, crossband, fitblend, trackmotion
from pxs.build import REPO, _frame_warnings, _frames
from pxs.centroid import JOINT
from pxs.manifest import measured_motion, validate
from pxs.validation.report import build_report

GALLERY = REPO / "web" / "gallery"
STACKS = REPO / "cache" / "astro"
# Lines `_frame_warnings` writes: replaced by the re-measured ones.
FRAME_LINES = ("The target saturates some frames", "The target was not detected in any frame",
               "No proper motion is known", "left out of the motion fit because")


def allow_joint_after_star_removal() -> None:
    """Patch `centroid` (this process only) so a star-subtracted frame is also fitted with
    its neighbours, as `detect` does for untouched frames."""
    measure, detect, seen = centroid._measure_peak, centroid.detect, {}

    def detect_(stack, predicted_px, pixscale_arcsec, search_radius, snr_min=centroid.SNR_MIN,
                avoid_px=(), neighbours_px=()):
        seen["known"] = neighbours_px
        return detect(stack, predicted_px, pixscale_arcsec, search_radius, snr_min, avoid_px,
                      neighbours_px)

    def measure_(fr, peak, stack, pixscale, known_px=(), snr_min=centroid.SNR_MIN, joint=True):
        return measure(fr, peak, stack, pixscale, known_px if joint else seen.get("known", ()),
                       snr_min, True)

    centroid.detect, centroid._measure_peak = detect_, measure_


def _same(a, b) -> bool:
    return a == b or bool(a and b and abs(a[0] - b[0]) < 2e-3 and abs(a[1] - b[1]) < 2e-3)


def refresh(slug: str) -> tuple[dict, dict, str]:
    """(published manifest, refreshed manifest, one line on the WISE frames)."""
    # our own pickle, written by dump_stacks.py
    d = pickle.loads((STACKS / f"{slug}.pkl").read_bytes())
    old = json.loads((GALLERY / slug / "manifest.json").read_text())
    gaia, catwise = old["overlays"].get("gaia", []), old["overlays"].get("catwise", [])
    t, grid = d["target"], d["grid"]
    wise = [s for s in d["stacks"] if s[1].mission == "WISE"]
    with tempfile.TemporaryDirectory() as tmp:  # the PNGs are not wanted here
        new, _ = _frames(t, grid, wise, Path(tmp), gaia, catwise)
    spx = [{**f, "warnings": [w for w in f["warnings"] if not w.startswith(fitblend.BLENDED)]}
           for f in old["frames"] if f["mission"] != "WISE"]
    frames = fitblend.flag(crossband.check([*new, *spx], grid.pixscale_arcsec), t, catwise,
                           grid.pixscale_arcsec)
    frames = sorted(frames, key=lambda f: (f["mjd"], f["id"]))
    kept = [w for w in old["warnings"] if not any(k in w for k in FRAME_LINES)
            and not w.startswith(trackmotion.NOTE[:40])]
    out = {**old, "frames": frames, "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "measured_motion": measured_motion(frames, grid, blend.target_parallax(t, gaia)),
           "warnings": list(dict.fromkeys([*kept, *_frame_warnings(frames, t)]))}
    out = trackmotion.fill(out, t, grid, d["stacks"], catwise)
    pub = {f["id"]: f["centroid_px"] for f in old["frames"]}
    w = [f for f in frames if f["mission"] == "WISE" and f["id"] in pub]
    joint = [f for f in w if any(n.startswith(JOINT) for n in f["warnings"])]
    changed = sum(not _same(f["centroid_px"], pub[f["id"]]) for f in w if f not in joint)
    line = (f"{len(w)} WISE frames: {len(joint)} fitted with a neighbour, {changed} changed "
            f"otherwise; blended {fitblend.n_blended(old['frames'])} -> "
            f"{fitblend.n_blended(frames)}")
    return old, out, line


def _row(mm: dict | None, cat: tuple[float, float]) -> str:
    if not mm:
        return "not measured"
    sr = (mm["pmra_masyr"] - cat[0]) / mm["err_pmra_masyr"]
    sd = (mm["pmdec_masyr"] - cat[1]) / mm["err_pmdec_masyr"]
    return (f"({mm['pmra_masyr']:9.2f}, {mm['pmdec_masyr']:9.2f}) +-({mm['err_pmra_masyr']:.2f}, "
            f"{mm['err_pmdec_masyr']:.2f})  sigma ({sr:+.2f}, {sd:+.2f})  n={mm['n_detections']} "
            f"chi2={mm['reduced_chi2']} {mm.get('method', '')}")


def main(argv: list[str]) -> int:
    if "--joint-after-star-removal" in argv:
        allow_joint_after_star_removal()
        argv = [a for a in argv if a != "--joint-after-star-removal"]
    out_dir = Path(argv[0])
    index = json.loads((GALLERY / "index.json").read_text())
    slugs = argv[1:] or [e["slug"] for e in index["targets"]
                         if (STACKS / f"{e['slug']}.pkl").exists()]
    manifests = {e["slug"]: json.loads((GALLERY / e["manifest"]).read_text())
                 for e in index["targets"]}
    for slug in slugs:
        old, new, line = refresh(slug)
        validate(new)
        (out_dir / slug).mkdir(parents=True, exist_ok=True)
        (out_dir / slug / "manifest.json").write_text(
            json.dumps(new, indent=1, allow_nan=False) + "\n")
        manifests[slug] = new
        cat = (old["target"]["pmra_masyr"], old["target"]["pmdec_masyr"])
        print(f"{slug}  catalogue {cat}\n   before: {_row(old['measured_motion'], cat)}\n"
              f"   after : {_row(new['measured_motion'], cat)}\n   {line}")
    report = build_report(index, manifests, json.loads((REPO / "data/targets.json").read_text()))
    (out_dir / "validation.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("scoreboard with the refreshed views:", report["summary"]["motion"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
