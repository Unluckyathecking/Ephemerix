"""List a phase's W1/W2 frames near a position from s3://nasa-irsa-wise alone (no IRSA query).

WISE scans along ecliptic meridians: within one scan every frame has the same ecliptic
longitude (header ``ELON0``, constant to 0.001 deg) and the ecliptic latitude changes by a
fixed step per frame number (about 0.63 deg). So two small header reads per scan (frames
near 100 and 160) give the scan's path, and from the path the frames that can touch a
position follow without reading the rest. Only those frames' full headers are then read;
each becomes a ``Frame`` with its WCS footprint, ``MJD_OBS`` and ``MOONSEP``.

Which frames are kept is the rule IRSA's TAP lookup applies (``search._tap``): W1 and W2
frames whose centre lies within the search radius plus ``FRAME_HALF_DIAGONAL_DEG``. The
bucket holds no frame-quality score (neither the headers nor any table there carry
``qual_frame``), so these frames have ``qual_frame=None`` and are screened downstream by
measured noise, as the 2010 frames listed by SIA already are.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pxs.wise.frames import Frame
from pxs.wise.phases import BANDS, bucket_key, phase
from pxs.wise.reader import CARD, frame_wcs, read_header
from pxs.wise.search import FRAME_HALF_DIAGONAL_DEG

log = logging.getLogger(__name__)

RangeFetch = Callable[[str, int, int], bytes]  # (key, start, stop) -> bytes, or raises
OBLIQUITY_DEG = 23.4392911  # J2000 mean obliquity
PATH_FRAMES = ((100, 160), (101, 161), (90, 150), (110, 170), (80, 140), (120, 180),
               (40, 100), (50, 110), (30, 90), (60, 120))  # short scans end near frame 140
PATH_BYTES = 80 * CARD  # MJD_OBS, ELON0 and ELAT0 are among the first 80 cards
WINDOW_PAD_FRAMES = 2  # extra frames each side of the predicted ones
CROSS_PAD_DEG = 0.1  # slack on the cross-scan test (the path model is good to ~0.01 deg)
WORKERS = 16


@dataclass(frozen=True)
class ScanPath:
    """One scan's track: ecliptic longitude, and along-track angle ``theta`` (equal to the
    ecliptic latitude on the near side of the pole) as a linear function of frame number."""

    scan_id: str
    elon_deg: float
    frame_a: int
    theta_a_deg: float
    step_deg: float  # theta change per frame number (signed)
    mjd: float  # time of frame_a


def to_ecliptic(ra: float, dec: float) -> tuple[float, float]:
    """(lon, lat) in degrees on the J2000 mean ecliptic."""
    a, d, e = map(math.radians, (ra, dec, OBLIQUITY_DEG))
    x, y, z = math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)
    ye, ze = y * math.cos(e) + z * math.sin(e), -y * math.sin(e) + z * math.cos(e)
    return math.degrees(math.atan2(ye, x)) % 360.0, math.degrees(math.asin(max(-1, min(1, ze))))


def track_coords(path: ScanPath, lon: float, lat: float) -> tuple[float, float]:
    """(cross-track, along-track theta) in degrees of an ecliptic position relative to the
    great circle through the ecliptic poles at the scan's longitude."""
    lam, beta, e = map(math.radians, (lon, lat, path.elon_deg))
    p = (math.cos(beta) * math.cos(lam), math.cos(beta) * math.sin(lam), math.sin(beta))
    u = (math.cos(e), math.sin(e))
    along_u = p[0] * u[0] + p[1] * u[1]
    cross = -p[0] * u[1] + p[1] * u[0]
    return math.degrees(math.asin(max(-1, min(1, cross)))), math.degrees(math.atan2(p[2], along_u))


def frame_window(path: ScanPath, lon: float, lat: float, reach_deg: float) -> list[int]:
    """Frame numbers of ``path`` whose centre may lie within ``reach_deg`` of the position
    (empty when the scan passes further away than that)."""
    cross, theta = track_coords(path, lon, lat)
    if abs(cross) > reach_deg + CROSS_PAD_DEG:
        return []
    half = math.sqrt(max(reach_deg**2 - cross**2, 0.0)) + CROSS_PAD_DEG
    ends = [path.frame_a + (theta + s * half - path.theta_a_deg) / path.step_deg for s in (-1, 1)]
    lo, hi = math.floor(min(ends)) - WINDOW_PAD_FRAMES, math.ceil(max(ends)) + WINDOW_PAD_FRAMES
    return list(range(max(lo, 0), min(hi, 999) + 1))


def _cards(raw: bytes) -> dict[str, str]:
    out = {}
    for i in range(0, len(raw) - CARD + 1, CARD):
        card = raw[i:i + CARD].decode("ascii", "replace")
        if card[8:10] == "= ":
            out[card[:8].strip()] = card[10:].split("/")[0].strip().strip("'").strip()
    return out


def path_from_cards(scan_id: str, a: tuple[int, dict], b: tuple[int, dict]) -> ScanPath:
    """A ScanPath from the header cards of two frames of one scan."""
    (fa, ca), (fb, cb) = a, b
    ta, tb = float(ca["ELAT0"]), float(cb["ELAT0"])
    return ScanPath(scan_id=scan_id, elon_deg=float(ca["ELON0"]), frame_a=fa, theta_a_deg=ta,
                    step_deg=(tb - ta) / (fb - fa), mjd=float(ca["MJD_OBS"]))


def scan_path(phase_name: str, scan_id: str, fetch: RangeFetch) -> ScanPath | None:
    """The scan's track from two small header reads, or None if no frame pair is readable."""
    for fa, fb in PATH_FRAMES:
        try:
            got = [(f, _cards(fetch(bucket_key(phase_name, scan_id, f, "W1"), 0, PATH_BYTES)))
                   for f in (fa, fb)]
        except Exception as exc:  # noqa: BLE001 - a frame missing from the scan: try another
            log.debug("%s %s frames %d/%d unreadable: %s", phase_name, scan_id, fa, fb, exc)
            continue
        if all("ELON0" in c and "ELAT0" in c for _, c in got):
            return path_from_cards(scan_id, *got)
    log.warning("no readable frame pair in %s scan %s", phase_name, scan_id)
    return None


def sia_corners(header) -> tuple[tuple[float, float], ...]:
    """The footprint IRSA's SIA lists for a frame: its WCS (with SIP) at FITS pixel
    coordinates -0.5 and NAXIS + 0.5 (so 1.5 px outside the first pixel's centre and 0.5 px
    outside the last one's). Checked 15 Nov 2026 on allsky, postcryo and NEOWISE frames: the
    SIA polygons land on those pixel coordinates to 0.01 px."""
    nx, ny = int(header["NAXIS1"]), int(header["NAXIS2"])
    px = [(-0.5, -0.5), (nx + 0.5, -0.5), (nx + 0.5, ny + 0.5), (-0.5, ny + 0.5)]
    return tuple((float(r), float(d)) for r, d in frame_wcs(header).all_pix2world(px, 1))


def frame_from_header(header, phase_name: str, scan_id: str, frame_num: int,
                      band: str, sia_footprint: bool = False) -> Frame:
    """A Frame from an L1b int header: WCS footprint (the corner pixels' centres, or SIA's
    convention with ``sia_footprint``), observation time, Moon distance."""
    corners = (sia_corners(header) if sia_footprint else
               tuple((float(r), float(d)) for r, d in frame_wcs(header).calc_footprint()))
    moon = header.get("MOONSEP")
    return Frame(phase=phase_name, scan_id=scan_id, frame_num=frame_num, band=band,
                 mjd=float(header["MJD_OBS"]), corners=corners, qual_frame=None,
                 moon_sep_deg=None if moon is None else float(moon), saa_sep_deg=None)


def centre_within(header, ra: float, dec: float, reach_deg: float) -> bool:
    """The TAP rule: frame centre (CRVAL) within ``reach_deg`` of (ra, dec)."""
    r1, d1, r2, d2 = map(math.radians, (header["CRVAL1"], header["CRVAL2"], ra, dec))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c)))) <= reach_deg


def _frame(phase_name: str, scan_id: str, frame_num: int, band: str, ra: float, dec: float,
           reach: float, fetch: RangeFetch, sia_footprint: bool = False) -> Frame | None:
    try:
        header, _ = read_header(bucket_key(phase_name, scan_id, frame_num, band), fetch)
    except Exception:  # noqa: BLE001 - frame numbers past the scan's end do not exist
        return None
    if not centre_within(header, ra, dec, reach):
        return None
    return frame_from_header(header, phase_name, scan_id, frame_num, band, sia_footprint)


def candidates(paths: Iterable[ScanPath], ra: float, dec: float,
               reach_deg: float) -> list[tuple[str, int]]:
    """(scan_id, frame_num) pairs whose centre may lie within ``reach_deg`` of (ra, dec)."""
    lon, lat = to_ecliptic(ra, dec)
    return [(p.scan_id, f) for p in paths for f in frame_window(p, lon, lat, reach_deg)]


def list_frames(phase_name: str, paths: Sequence[ScanPath], ra: float, dec: float,
                radius_deg: float, fetch: RangeFetch, workers: int = WORKERS,
                sia_footprint: bool = False) -> list[Frame]:
    """W1/W2 frames of a phase near a circle, selected as IRSA's TAP lookup selects them."""
    phase(phase_name)  # validate the name
    reach = radius_deg + FRAME_HALF_DIAGONAL_DEG
    jobs = [(s, f, b) for s, f in candidates(paths, ra, dec, reach) for b in BANDS]
    with ThreadPoolExecutor(workers) as ex:
        found = ex.map(lambda j: _frame(phase_name, *j, ra, dec, reach, fetch, sia_footprint),
                       jobs)
        frames = [f for f in found if f is not None]
    log.info("%s from the bucket at %.5f %.5f: %d header reads -> %d frames", phase_name,
             ra, dec, len(jobs), len(frames))
    return sorted(frames, key=lambda f: (f.mjd, f.key))
