"""Write web/data/data-status.json: how current the SPHEREx data behind the site is.

    python3 tools/data_status.py                    # fetch manifest.json from the Modal volume
    python3 tools/data_status.py --manifest PATH    # or read a local copy

Two sources, kept apart: the frame index (manifest.json on the `pxs-index` volume, written by
tools/spherex_index) and the built gallery views (web/gallery/*/manifest.json). They can differ,
because the index covers every frame in the archive and the gallery only the views we built.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "data-status.json"
GALLERY = ROOT / "web" / "gallery"
VOLUME = "pxs-index"
MJD_EPOCH = datetime(1858, 11, 17)


def mjd_to_date(mjd: float) -> str:
    """UTC calendar day of a modified Julian date, as YYYY-MM-DD."""
    return (MJD_EPOCH + timedelta(days=mjd)).date().isoformat()


def index_part(manifest: dict) -> dict:
    """Releases, frame counts and dates from the index manifest; raises ValueError if it is off."""
    try:
        releases = [{"name": name.upper(), "frames": int(r["rows"]), "newest_frame": mjd_to_date(float(r["mjd_max"])),
                     "mjd_max": float(r["mjd_max"])}
                    for name, r in sorted(manifest["releases"].items()) if int(r["rows"]) > 0]
        total = int(manifest["rows"])
        built = str(manifest["built_at"])[:10]
        datetime.fromisoformat(built)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"index manifest is missing or malformed: {e!r}") from e
    if not releases:
        raise ValueError("index manifest lists no releases with frames")
    if total != sum(r["frames"] for r in releases):
        raise ValueError("index total does not equal the sum over releases")
    return {"source": f"manifest.json on the Modal volume {VOLUME} (tools/spherex_index)",
            "code_version": manifest.get("code_version"), "releases": releases, "frames_total": total,
            "newest_frame": max(r["newest_frame"] for r in releases), "refreshed": built}


def gallery_part(views: list[dict]) -> dict:
    """Newest SPHEREx frame shown in any built view, and when the latest view was built."""
    dates = [f["date"][:10] for v in views for f in v.get("frames", []) if f.get("mission") == "SPHEREx"]
    built = [v["generated"][:10] for v in views if v.get("generated")]
    if not dates or not built:
        raise ValueError("no SPHEREx frames or no build date in the gallery views")
    return {"source": "web/gallery/*/manifest.json", "views": len(views), "spherex_frames": len(dates),
            "newest_frame": max(dates), "built": max(built)}


def build_status(manifest: dict, views: list[dict], generated: str) -> dict:
    return {"schema": 1, "generated": generated, "index": index_part(manifest), "gallery": gallery_part(views)}


def load_gallery(root: Path = GALLERY) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(root.glob("*/manifest.json"))]


def fetch_manifest() -> dict:
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["modal", "volume", "get", VOLUME, "/manifest.json", d, "--force"], check=True)
        return json.loads((Path(d) / "manifest.json").read_text())


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", type=Path, help="local copy of the index manifest.json")
    a = ap.parse_args(argv)
    manifest = json.loads(a.manifest.read_text()) if a.manifest else fetch_manifest()
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    status = build_status(manifest, load_gallery(), now)
    OUT.write_text(json.dumps(status, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
