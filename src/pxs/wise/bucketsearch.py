"""WISE frames near a position from s3://nasa-irsa-wise alone, for when IRSA's search is down.

``search.search_frames`` calls ``phase_frames`` for a phase that neither IRSA service listed.
Frames are chosen by the rule IRSA's TAP lookup applies (``bucketlist``): a W1/W2 frame whose
centre lies within the search radius plus ``FRAME_HALF_DIAGONAL_DEG``. That is a superset the
caller tests footprint by footprint, exactly as it tests TAP rows. Each footprint is the
polygon IRSA's SIA would have listed (``bucketlist.sia_corners``), so the frames kept for a
target are the ones the normal path keeps; frame times are the header's ``MJD_OBS``, 3 to 5 s
later than SIA's ``t_min``.

2010-2011 (allsky, 3band, postcryo): the track of every scan is committed beside this module
(``scantracks/<phase>.json``; 11,731 of the 11,743 scans, two small header reads each, by
``python -m pxs.wise.bucketsearch --write-tracks``). ``bucketlist.list_frames`` picks the
frames from the tracks and reads their headers. The bucket holds no quality score for these
phases, so ``qual_frame`` is None and the stacker screens them by measured noise.

2013-2024 (neowiser): about 120,000 scans, too many for a committed file, but the NEOWISE
source table in the bucket (``neoqual``) names every frame with an extracted source in the
HEALPix pixels around the position, with its quality score: a few thousand frames. The
centre of each is read from the first cards of its W1 header (not cached: they are one-off
probes), and the ones within reach have both bands' headers read for footprint and time. A
frame with no source at all near the position is not named; such a frame is unusable anyway.

Nothing here raises to the caller: ``phase_frames`` returns None when a phase cannot be
listed, and the caller reports that phase as missing, as before.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pyarrow.fs as pafs
import requests

from pxs.wise import bucketlist, neoqual, net
from pxs.wise.bucketlist import ScanPath
from pxs.wise.frames import Frame
from pxs.wise.phases import BANDS, bucket_key, phase

log = logging.getLogger(__name__)

# Every scan passes over the ecliptic poles, so listing a position within 3 degrees of one
# means 20,000 to 140,000 header reads. The phase is reported as missing instead.
POLE_LAT_DEG = 87.0

TRACK_DIR = Path(__file__).parent / "scantracks"
TRACK_PHASES = ("allsky", "3band", "postcryo")
NEOWISE = "neowiser"
FRAME_HALF_DIAGONAL_DEG = bucketlist.FRAME_HALF_DIAGONAL_DEG
PROBE_PAD_DEG = 0.05  # W1 and W2 centres differ by arcseconds; the exact test is per band
PROBE_WORKERS = 32  # the session's connection pool size (net)
_GONE = (403, 404)  # a frame the source table names but the bucket does not hold

RangeFetch = Callable[[str, int, int], bytes]
_probe: RangeFetch = functools.partial(net.get_range, cache=False)


@functools.cache
def tracks(phase_name: str) -> tuple[ScanPath, ...]:
    """The committed scan tracks of a 2010-2011 phase."""
    rows = json.loads((TRACK_DIR / f"{phase_name}.json").read_text())
    return tuple(ScanPath(scan_id=s, elon_deg=lon, frame_a=fa, theta_a_deg=theta, step_deg=step,
                          mjd=mjd) for s, lon, fa, theta, step, mjd in rows)


def _centre_near(scan_id: str, frame_num: int, ra: float, dec: float, reach_deg: float,
                 probe: RangeFetch) -> bool:
    """True when the W1 frame's centre is within reach, or the W1 file is not in the bucket
    (the W2 one may be). Any other failure raises: a frame must not be lost to a bad read."""
    key = bucket_key(NEOWISE, scan_id, frame_num, "W1")
    try:
        cards = bucketlist._cards(probe(key, 0, bucketlist.PATH_BYTES))
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in _GONE:
            return True
        raise
    return bucketlist.centre_within({"CRVAL1": float(cards["CRVAL1"]),
                                     "CRVAL2": float(cards["CRVAL2"])}, ra, dec, reach_deg)


def neowise_frames(ra: float, dec: float, radius_deg: float, *,
                   scores: neoqual.Quality | None = None, probe: RangeFetch | None = None,
                   fetch: RangeFetch | None = None) -> list[Frame]:
    """NEOWISE W1/W2 frames near a circle, with ``qual_frame`` from the source table."""
    if scores is None:
        scores = neoqual.read_scores(ra, dec, radius_deg)
    probe, fetch = probe or _probe, fetch or net.get_range
    reach = radius_deg + FRAME_HALF_DIAGONAL_DEG
    named = sorted(scores)
    with ThreadPoolExecutor(PROBE_WORKERS) as ex:
        near = list(ex.map(lambda sf: _centre_near(*sf, ra, dec, reach + PROBE_PAD_DEG, probe),
                           named))
        jobs = [(s, f, b) for (s, f), ok in zip(named, near) if ok for b in BANDS]
        found = list(ex.map(lambda j: bucketlist._frame(NEOWISE, *j, ra, dec, reach, fetch,
                                                        sia_footprint=True), jobs))
    frames = []
    for f in found:
        if f is not None:
            q, saa = scores[(f.scan_id, f.frame_num)]
            frames.append(replace(f, qual_frame=q, saa_sep_deg=saa))
    log.info("neowiser from the bucket at %.5f %.5f: %d frames named, %d header reads -> %d "
             "frames", ra, dec, len(named), len(jobs), len(frames))
    return sorted(frames, key=lambda f: (f.mjd, f.key))


def phase_frames(phase_name: str, ra: float, dec: float, radius_deg: float) -> list[Frame] | None:
    """A phase's frames near a circle with no IRSA query, or None when that failed."""
    if abs(bucketlist.to_ecliptic(ra, dec)[1]) > POLE_LAT_DEG:
        log.warning("WISE %s frames from the bucket skipped at %.5f %.5f: every scan crosses "
                    "the ecliptic poles", phase_name, ra, dec)
        return None
    t0 = time.monotonic()
    try:
        if phase_name == NEOWISE:
            frames = neowise_frames(ra, dec, radius_deg)
        else:
            frames = bucketlist.list_frames(phase_name, tracks(phase_name), ra, dec, radius_deg,
                                            net.get_range, sia_footprint=True)
    except Exception as exc:  # noqa: BLE001 - the caller reports the phase as missing
        log.warning("WISE %s frames from the bucket failed (%s: %s)", phase_name,
                    type(exc).__name__, exc)
        return None
    log.info("WISE %s listed from the bucket: %d frames in %.1f s", phase_name, len(frames),
             time.monotonic() - t0)
    return frames


def scan_ids(phase_name: str) -> list[str]:
    """Every scan directory of a phase in the bucket."""
    fs = pafs.S3FileSystem(anonymous=True, region=neoqual.BUCKET_REGION)
    root = "nasa-irsa-wise/" + phase(phase_name).bucket_prefix.rstrip("/")
    groups = [g.path for g in fs.get_file_info(pafs.FileSelector(root))]
    return sorted(i.base_name for g in groups for i in fs.get_file_info(pafs.FileSelector(g)))


def _scan_path(phase_name: str, scan_id: str) -> ScanPath | None:
    return bucketlist.scan_path(phase_name, scan_id, _probe)


def write_tracks(out: Path = TRACK_DIR) -> None:
    """Read every 2010-2011 scan's track from the bucket and write ``<phase>.json``."""
    out.mkdir(parents=True, exist_ok=True)
    for name in TRACK_PHASES:
        ids = scan_ids(name)
        with ThreadPoolExecutor(PROBE_WORKERS) as ex:
            found = ex.map(functools.partial(_scan_path, name), ids)
            paths = [p for p in found if p is not None]
        rows = [[p.scan_id, round(p.elon_deg, 6), p.frame_a, round(p.theta_a_deg, 6),
                 round(p.step_deg, 8), round(p.mjd, 6)] for p in paths]
        (out / f"{name}.json").write_text(json.dumps(rows, separators=(",", ":")) + "\n")
        log.info("%s: %d of %d scans have a track", name, len(rows), len(ids))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write-tracks", action="store_true", required=True)
    ap.add_argument("--out", type=Path, default=TRACK_DIR)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    write_tracks(args.out)


if __name__ == "__main__":
    main()
