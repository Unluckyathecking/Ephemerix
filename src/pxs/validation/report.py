"""Assemble validation.json from the gallery manifests and data/targets.json."""

import json
import sys
from pathlib import Path

from pxs.validation.rules import (
    EXPLANATIONS,
    FAIL,
    FAINT,
    MOTION_SIGMA,
    NOT_APPLICABLE,
    PASS,
    REFUSED,
    THRESHOLDS,
    all_frames_note,
    motion_check,
    second_reference,
    type_check,
)
from pxs.validation.stats import (
    declined_reason,
    degraded_info,
    frame_stats,
    motion_missing_reason,
    residual_info,
)

ROOT = Path(__file__).resolve().parents[3]
GALLERY = ROOT / "web" / "gallery"
TARGETS = ROOT / "data" / "targets.json"
OUT = ROOT / "web" / "data" / "validation.json"


def _round(x, nd=3):
    """Round every float in a nested structure so reruns give identical text."""
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _round(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v, nd) for v in x]
    return x


def target_report(entry: dict, manifest: dict, published: dict | None) -> dict:
    """One scoreboard row. `published` is the data/targets.json entry, or None."""
    t = manifest.get("target", {})
    source = published or t
    catalogue = {"pmra_masyr": source.get("pmra_masyr"), "pmdec_masyr": source.get("pmdec_masyr"),
                 "source": (published or {}).get("pm_source")}
    known = (published or {}).get("known_type") or entry.get("known_type")
    spectra = manifest.get("spectra") or []
    motion = motion_check(manifest.get("measured_motion"), catalogue, motion_missing_reason(manifest))
    note = EXPLANATIONS.get((entry["slug"], "motion")) if motion["verdict"] == FAIL else None
    note = " ".join(n for n in (all_frames_note(motion), note) if n) or None
    second = second_reference(manifest.get("measured_motion"),
                              (published or {}).get("pm_second_reference"))
    typ = type_check(manifest.get("match"), known, bool(spectra), declined_reason(manifest))
    return {
        "slug": entry["slug"], "name": entry["name"], "group": entry.get("group"),
        "known_type": known,
        "known_type_ref": (published or {}).get("known_type_ref"),
        "motion": {**motion, "note": note, "second_reference": second},
        "type": typ, "degraded": degraded_info(manifest),
        "frames": frame_stats(manifest), "residual": residual_info(manifest),
        "generated": manifest.get("generated"),
    }


def summarise(rows: list[dict]) -> dict:
    """The counts for the summary row. A type given to a faint object from a fit to all its
    points (provisional_kind "faint") is counted apart, in `type.faint`, and is in none of
    `type.passed`, `type.failed`, `type.total` or `type.provisional`."""
    def block(check: str, among: list[dict]) -> dict:
        def count(verdict: str) -> int:
            return sum(1 for r in among if r[check]["verdict"] == verdict)

        p, f = count(PASS), count(FAIL)
        return {"passed": p, "failed": f, "total": p + f, "refused": count(REFUSED),
                "not_applicable": count(NOT_APPLICABLE)}

    faint = [r for r in rows if r["type"].get("provisional_kind") == FAINT]
    usual = [r for r in rows if r["type"].get("provisional_kind") != FAINT]
    types = {**block("type", usual),
             "provisional": sum(1 for r in usual if r["type"].get("provisional")),
             "faint": {"passed": sum(1 for r in faint if r["type"]["verdict"] == PASS),
                       "failed": sum(1 for r in faint if r["type"]["verdict"] == FAIL),
                       "open_ended": sum(1 for r in faint if r["type"].get("range_open_warm")
                                         or r["type"].get("range_open_cold"))}}
    return {"targets": len(rows), "motion": block("motion", rows), "type": types,
            "degraded": sum(1 for r in rows if r["degraded"]["flag"])}


def build_report(index: dict, manifests: dict[str, dict], published: list[dict]) -> dict:
    """Pure: index.json, {slug: manifest}, data/targets.json entries -> the report.

    Solar System body views have no proper-motion fit or spectral type and are left out.
    """
    by_slug = {p["slug"]: p for p in published}
    rows = [target_report(e, manifests[e["slug"]], by_slug.get(e["slug"]))
            for e in index["targets"] if not manifests[e["slug"]].get("solar_system")]
    stars = [m for m in manifests.values() if not m.get("solar_system")]
    built = max((m.get("generated") or "" for m in stars), default="") or None
    return _round({
        "schema": 1, "built": built,
        "thresholds": {**THRESHOLDS, "motion_sigma": MOTION_SIGMA},
        "summary": summarise(rows), "targets": rows,
    })


def write_report(gallery: Path = GALLERY, targets: Path = TARGETS, out: Path = OUT) -> dict:
    index = json.loads((gallery / "index.json").read_text())
    manifests = {e["slug"]: json.loads((gallery / e["manifest"]).read_text())
                 for e in index["targets"]}
    report = build_report(index, manifests, json.loads(targets.read_text()))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return report


def main() -> int:
    s = write_report()["summary"]
    print(f"motion {s['motion']['passed']}/{s['motion']['total']} passed; "
          f"type {s['type']['passed']}/{s['type']['total']} passed, "
          f"{s['type']['refused']} refused, {s['type']['provisional']} provisional, "
          f"{s['type']['faint']['passed']}/"
          f"{s['type']['faint']['passed'] + s['type']['faint']['failed']} faint types passed "
          "(counted apart); "
          f"{s['degraded']}/{s['targets']} degraded "
          f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
