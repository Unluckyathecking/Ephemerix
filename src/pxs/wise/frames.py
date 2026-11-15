"""The Frame record and parsers for IRSA SIA2 and TAP frame listings.

SIA2 gives each frame's footprint polygon but no quality score; the TAP ``*_p1bm_frm`` tables
give ``qual_frame`` (0 bad, 5 usable, 10 best), Moon and SAA distances and the footprint
corners. SIA2's 3-band collection is empty (checked 14 Nov 2026 at several positions and a
30-degree cone), while the TAP 3-band table has frames that exist in the bucket, so frames
seen only in TAP are kept.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, replace

from pxs.wise.phases import BANDS, bucket_key, phase_of_url

Corners = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Frame:
    """One W1 or W2 single exposure. Angles in degrees, time in MJD (UTC)."""

    phase: str
    scan_id: str
    frame_num: int
    band: str
    mjd: float
    corners: Corners  # footprint vertices (ra, dec), in order
    qual_frame: int | None = None  # None when TAP had no row for this frame
    moon_sep_deg: float | None = None
    saa_sep_deg: float | None = None

    @property
    def key(self) -> str:
        return bucket_key(self.phase, self.scan_id, self.frame_num, self.band)

    @property
    def ident(self) -> tuple[str, str, int, str]:
        return (self.phase, self.scan_id, self.frame_num, self.band)


def _polygon(s_region: str) -> Corners:
    """Vertices of an SIA ``POLYGON ICRS ra dec ...`` string, without the closing repeat."""
    vals = [float(v) for v in s_region.split()[2:]]
    pts = tuple(zip(vals[0::2], vals[1::2]))
    return pts[:-1] if len(pts) > 3 and pts[0] == pts[-1] else pts


def parse_sia(text: str) -> list[Frame]:
    """W1/W2 int frames from an SIA2 CSV response (other products and bands are skipped)."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        url = row.get("access_url") or ""
        band = row.get("energy_bandpassname")
        if row.get("dataproduct_subtype") != "science" or band not in BANDS:
            continue
        if not url.endswith("-int-1b.fits"):  # Atlas coadd tiles are also "science"
            continue
        _, scan_id, frame_num = row["obs_id"].split("_")
        out.append(Frame(phase=phase_of_url(url).name, scan_id=scan_id,
                         frame_num=int(frame_num), band=band, mjd=float(row["t_min"]),
                         corners=_polygon(row["s_region"])))
    return out


def _opt_float(value: str) -> float | None:
    return float(value) if value.strip() else None


def parse_tap(text: str, phase_name: str) -> list[Frame]:
    """W1/W2 frames from a CSV TAP query on a ``*_p1bm_frm`` table (columns as in TAP_COLUMNS)."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        band = f"W{int(row['band'])}"
        if band not in BANDS:
            continue
        corners = tuple((float(row[f"ra{i}"]), float(row[f"dec{i}"])) for i in range(1, 5))
        qual = row["qual_frame"].strip()
        out.append(Frame(phase=phase_name, scan_id=row["scan_id"].strip(),
                         frame_num=int(row["frame_num"]), band=band,
                         mjd=float(row["mjd_obs"]), corners=corners,
                         qual_frame=int(qual) if qual else None,
                         moon_sep_deg=_opt_float(row["moon_sep"]),
                         saa_sep_deg=_opt_float(row["saa_sep"])))
    return out


TAP_COLUMNS = ("scan_id, frame_num, band, qual_frame, moon_sep, saa_sep, mjd_obs, "
               "ra1, dec1, ra2, dec2, ra3, dec3, ra4, dec4")


def merge(sia: Iterable[Frame], tap: Iterable[Frame]) -> list[Frame]:
    """Union of SIA and TAP frames, with TAP quality attached to SIA frames; sorted by time.

    SIA frames keep their footprint and gain ``qual_frame``, Moon and SAA distances from the
    matching TAP row. Frames with no TAP row keep ``qual_frame=None``. TAP-only frames are
    kept (the caller tests their footprint against the target).
    """
    by_id = {f.ident: f for f in tap}
    out = {}
    for f in sia:
        t = by_id.get(f.ident)
        out[f.ident] = f if t is None else replace(
            f, qual_frame=t.qual_frame, moon_sep_deg=t.moon_sep_deg, saa_sep_deg=t.saa_sep_deg)
    for ident, t in by_id.items():
        out.setdefault(ident, t)
    return sorted(out.values(), key=lambda f: (f.mjd, f.key))
