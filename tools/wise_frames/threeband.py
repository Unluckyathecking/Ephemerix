"""Fill the 2010 three-band phase of data/frames/wise/<slug>.json from the bucket alone.

    PYTHONPATH=src:tools python -m wise_frames.threeband [slug ...] [--dir data/frames/wise]
    PYTHONPATH=src:tools python -m wise_frames.threeband --check-allsky slug

Only IRSA's TAP lists the three-band frames, and TAP is often down. The frames themselves
are in s3://nasa-irsa-wise, and ``pxs.wise.bucketlist`` finds the ones near a position from
the scans' tracks (two small header reads per scan, about 1,640 scans, read once and cached
under cache/wise-bucket/), then reads the candidate frames' headers. The list's other phases
and rows are left exactly as they were.

``--check-allsky`` runs the same search on the 2010 cryogenic phase over the scans of the
target's listed allsky visit and compares with the frames IRSA SIA listed there.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.fs as pafs
import requests

from pxs.wise import bucketlist, framelist
from pxs.wise.bucketlist import ScanPath
from pxs.wise.frames import Frame
from pxs.wise.geometry import edge_distance_arcsec
from pxs.wise.phases import bucket_key, phase

log = logging.getLogger("wise_frames")

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "cache" / "wise-bucket"
BUCKET = "nasa-irsa-wise"
BUCKET_URL = f"https://{BUCKET}.s3.amazonaws.com/"
USER_AGENT = "wise-frames/1.0"
HOW = ("s3://nasa-irsa-wise headers (pxs.wise.bucketlist; no IRSA): frames whose centre is "
       "within the list radius + 0.6 deg, as IRSA TAP selects them; no qual_frame in the "
       "bucket, so these frames are screened by measured noise")

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=bucketlist.WORKERS))


def fetch(key: str, start: int, stop: int) -> bytes:
    """Bytes [start, stop) of a bucket object, cached under cache/wise-bucket/s3/."""
    path = CACHE / "s3" / f"{key}.{start}-{stop}"
    if path.exists():
        return path.read_bytes()
    resp = _session.get(BUCKET_URL + key, headers={"Range": f"bytes={start}-{stop - 1}"},
                        timeout=(5, 30))
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(resp.content)
    os.replace(tmp, path)
    return resp.content


def scan_ids(phase_name: str) -> list[str]:
    """Every scan directory of a phase in the bucket (about 4 s for the three-band phase)."""
    fs = pafs.S3FileSystem(anonymous=True, region="us-west-2")
    root = BUCKET + "/" + phase(phase_name).bucket_prefix.rstrip("/")
    groups = [g.path for g in fs.get_file_info(pafs.FileSelector(root))]
    return sorted(i.base_name for g in groups for i in fs.get_file_info(pafs.FileSelector(g)))


def scan_paths(phase_name: str, ids: list[str]) -> list[ScanPath]:
    with ThreadPoolExecutor(bucketlist.WORKERS) as ex:
        paths = ex.map(lambda s: bucketlist.scan_path(phase_name, s, fetch), ids)
        return [p for p in paths if p is not None]


@functools.cache
def threeband_paths() -> tuple[ScanPath, ...]:
    """Tracks of every three-band scan (read once per process; bytes cached on disk)."""
    return tuple(scan_paths("3band", scan_ids("3band")))


def bucket_frames(ra: float, dec: float, radius_deg: float) -> list[Frame] | None:
    """Three-band frames near a circle from the bucket, or None if the bucket route failed."""
    try:
        return bucketlist.list_frames("3band", threeband_paths(), ra, dec, radius_deg, fetch)
    except Exception as exc:  # noqa: BLE001 - the caller falls back to the timing rule
        log.warning("three-band frames from the bucket failed: %s", exc)
        return None


def _sort_key(row: list) -> tuple:
    return (row[4], bucket_key(row[0], row[1], row[2], row[3]))


def patch(doc: dict, frames: list[Frame], how: str = HOW) -> dict:
    """A copy of a frame list with its three-band phase replaced by ``frames``."""
    rows = [r for r in doc["frames"] if r[0] != "3band"] + [framelist.to_row(f) for f in frames]
    phases = {k: dict(v) for k, v in doc["phases"].items()}
    phases["3band"] = {"status": "complete" if frames else "none", "how": how,
                       "frames": len(frames)}
    return {**doc, "phases": phases, "frames": sorted(rows, key=_sort_key)}


def fill(path: Path, paths: list[ScanPath]) -> dict:
    doc = framelist.load(path)
    frames = bucketlist.list_frames("3band", paths, doc["ra"], doc["dec"], doc["radius_deg"],
                                    fetch)
    new = patch(doc, frames)
    framelist._check(new)
    path.write_text(json.dumps(new, separators=(",", ":")) + "\n")
    return new


def check_allsky(path: Path) -> None:
    """Search the allsky phase from the bucket over the listed allsky visit's scans, and
    compare with the SIA-listed allsky frames."""
    doc = framelist.load(path)
    listed = {(r[1], r[2], r[3]) for r in doc["frames"] if r[0] == "allsky"}
    nums = sorted(int(s[:5]) for s, _, _ in listed)
    ids = [s for s in scan_ids("allsky") if nums[0] - 30 <= int(s[:5]) <= nums[-1] + 30]
    found = bucketlist.list_frames("allsky", scan_paths("allsky", ids), doc["ra"], doc["dec"],
                                   doc["radius_deg"], fetch)
    corners = {(f.scan_id, f.frame_num, f.band): f for f in found}
    hits = {k for k, f in corners.items()
            if any_overlap(f, doc["ra"], doc["dec"], doc["radius_deg"])}
    print(f"{path.stem}: SIA allsky {len(listed)}; bucket {len(found)} (TAP rule), "
          f"{len(hits)} overlapping the circle; SIA not found: {sorted(listed - set(corners))}; "
          f"overlapping but not in SIA: {sorted(hits - listed)}")


def any_overlap(f: Frame, ra: float, dec: float, radius_deg: float) -> bool:
    """Roughly: does the footprint come within the radius of the centre."""
    return edge_distance_arcsec(f.corners, ra, dec) > -radius_deg * 3600


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slugs", nargs="*", help="lists to fill (default: all)")
    ap.add_argument("--dir", type=Path, default=framelist.DEFAULT_DIR)
    ap.add_argument("--check-allsky", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    files = [p for p in sorted(args.dir.glob("*.json")) if not args.slugs or p.stem in args.slugs]
    if args.check_allsky:
        for p in files:
            check_allsky(p)
        return
    paths = list(threeband_paths())
    log.info("%d three-band scan tracks", len(paths))
    for p in files:
        new = fill(p, paths)
        log.info("%s: 3band %s", p.stem, new["phases"]["3band"])


if __name__ == "__main__":
    main()
