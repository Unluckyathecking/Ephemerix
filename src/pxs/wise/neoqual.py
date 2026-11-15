"""NEOWISE frame-quality scores from the public source table, with no IRSA query.

IRSA's NEOWISE-R single-exposure source table (``p1bs_psd``) sits in s3://nasa-irsa-wise as
Parquet, one file per HEALPix order-5 pixel (nested) per release year. Every source row
carries its frame's ``scan_id``, ``frame_num``, ``qual_frame`` and ``saa_sep``. Those columns
are dictionary/RLE encoded, so reading just them costs about 200 kB per pixel-year (about
3 s for all twelve releases of one pixel from the UK), against 400 MB for the whole file.

Checked 14 Nov 2026: frame 87696a155, the one qual 0 frame IRSA's TAP gave at WISE 0855,
has qual_frame 0 here too, and no frame has two different scores across its rows. The score
is per frameset (W1 and W2 together); TAP's frame table lists it per band.

A frame with no extracted source near the target is absent, so its score stays unknown.
``quality`` never raises: on any failure it returns what it has (possibly nothing).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import astropy.units as u
import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq
from astropy_healpix import HEALPix

log = logging.getLogger(__name__)

BUCKET_REGION = "us-west-2"
ROOT = "nasa-irsa-wise/wise/neowiser/catalogs/p1bs_psd/healpix_k5/"
RELEASES = tuple(f"year{i}" for i in range(1, 12)) + ("addendum",)
COLUMNS = ["scan_id", "frame_num", "qual_frame", "saa_sep"]
NSIDE = 32  # order 5
PAD_DEG = 0.05  # frames covering the target have sources within this of it
WORKERS = 12

Quality = dict[tuple[str, int], tuple[int | None, float | None]]  # (scan, frame) -> (q, saa)

_HP = HEALPix(nside=NSIDE, order="nested")


def pixels(ra: float, dec: float, radius_deg: float) -> list[int]:
    """Order-5 nested HEALPix pixels touching the circle (padded by PAD_DEG)."""
    found = _HP.cone_search_lonlat(ra * u.deg, dec * u.deg, (radius_deg + PAD_DEG) * u.deg)
    return sorted(int(p) for p in found)


def partition_dir(release: str, pix: int) -> str:
    return (f"{ROOT}{release}/neowiser-healpix_k5-{release}.parquet/"
            f"healpix_k0={pix >> 10}/healpix_k5={pix}")


def _read(fs: pafs.FileSystem, release: str, pix: int) -> list[pa.Table]:
    try:
        infos = fs.get_file_info(pafs.FileSelector(partition_dir(release, pix)))
    except FileNotFoundError:  # the addendum covers only part of the sky
        return []
    return [pq.ParquetFile(fs.open_input_file(i.path), pre_buffer=False).read(columns=COLUMNS)
            for i in infos if i.path.endswith(".parquet")]


def scores(tables: list[pa.Table]) -> Quality:
    """One (qual_frame, saa_sep) per frame; the lowest score wins if rows ever disagree."""
    if not tables:
        return {}
    t = pa.concat_tables(tables, promote_options="permissive").group_by(["scan_id", "frame_num"]).aggregate(
        [("qual_frame", "min"), ("saa_sep", "min")])
    cols = [t.column(c).to_pylist()
            for c in ("scan_id", "frame_num", "qual_frame_min", "saa_sep_min")]
    return {(s, int(n)): (q, saa) for s, n, q, saa in zip(*cols)}


def read_scores(ra: float, dec: float, radius_deg: float,
                fs: pafs.FileSystem | None = None) -> Quality:
    """NEOWISE frame scores near a circle (degrees), keyed by (scan_id, frame_num): every
    frame with an extracted source in the HEALPix pixels the circle touches. Raises when the
    table cannot be read, so "unreadable" is never taken for "no frames"."""
    fs = fs or pafs.S3FileSystem(anonymous=True, region=BUCKET_REGION)
    jobs = [(r, p) for p in pixels(ra, dec, radius_deg) for r in RELEASES]
    with ThreadPoolExecutor(WORKERS) as ex:
        parts = list(ex.map(lambda job: _read(fs, *job), jobs))
    out = scores([t for part in parts for t in part])
    log.info("NEOWISE quality for %.5f %.5f: %d frames from %d partition reads",
             ra, dec, len(out), len(jobs))
    return out


def quality(ra: float, dec: float, radius_deg: float,
            fs: pafs.FileSystem | None = None) -> Quality:
    """``read_scores``, but never raising: on any failure the result is empty."""
    try:
        return read_scores(ra, dec, radius_deg, fs)
    except Exception as exc:  # noqa: BLE001 - optional: missing scores are handled downstream
        log.warning("NEOWISE quality from the source table failed (%s: %s)",
                    type(exc).__name__, exc)
        return {}
