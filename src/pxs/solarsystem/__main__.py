"""CLI: python -m pxs.solarsystem --body <designation> --out <dir> [--no-stacks] [--no-control]

Writes <out>/<slug>/manifest.json with its images, and prints a one-line summary per pass.
The designation must be in data/bodies.json or match a strict pattern (see bodies.resolve).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pxs.manifest import ManifestError, validate

from . import bodymanifest
from .bodies import resolve
from .pipeline import run_body

log = logging.getLogger("pxs.solarsystem")


def check(manifest: dict, root: Path) -> list[str]:
    """Problems with the schema-1 part of the manifest (empty when it validates)."""
    if not manifest["frames"]:
        return ["no sky-fixed frames (body not detected or not moving)"]
    try:
        validate(manifest, root)
    except ManifestError as e:
        return str(e).splitlines()[1:]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.solarsystem", description=__doc__)
    ap.add_argument("--body", required=True, help="designation, e.g. 136108 or Haumea")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-stacks", action="store_true")
    ap.add_argument("--no-control", action="store_true")
    ap.add_argument("--max-passes", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        body = resolve(a.body)
    except ValueError as e:
        log.error("%s", e)
        return 2
    run = run_body(body, with_stacks=not a.no_stacks, with_control=not a.no_control,
                   max_passes=a.max_passes)
    root = a.out / body.slug
    root.mkdir(parents=True, exist_ok=True)
    m = bodymanifest.build(run, root)
    problems = check(m, root)
    if problems:
        log.warning("schema-1 part does not validate: %s", "; ".join(problems))
    (root / "manifest.json").write_text(json.dumps(m, indent=1, allow_nan=False))
    for p in m["solar_system"]["passes"]:
        log.warning("%s %s..%s: %d/%d frames, best %s S/N %s, %s", body.name,
                    p["date_start"][:10], p["date_end"][:10], p["n_measured"], p["n_frames"],
                    p["best_band"], p["best_snr"], p["outcome"])
    log.warning("timings (s): %s", m["solar_system"]["timings_s"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
