"""WISE/NEOWISE single-exposure (L1b) frames: find them via IRSA SIA2, read stamps from the
public AWS bucket s3://nasa-irsa-wise with HTTP range reads.

Building blocks for the pipeline:
  find_frames(ra, dec)            -> list[Frame]   (4 SIA2 queries in parallel, ~5 s)
  read_stamp(frame, ra, dec, r)   -> Stamp | None  (2 range GETs: header, then the needed rows)

Bucket layout (verified 14 Nov 2026), plain uncompressed FITS (int) next to gzipped msk/unc:
  wise/allsky/images/4band_p1bm_frm/  (2010 full cryo)      SIA collection wise_allsky
  wise/cryo-3band/images/3band_p1bm_frm/ (2010 3-band)      SIA collection wise_3bandcryo
  wise/postcryo/images/2band_p1bm_frm/   (2010-11 post-cryo) SIA collection wise_2bandcryo
  wise/neowiser/images/p1bm_frm/         (NEOWISE-R 2013-24) SIA collection neowiser
  .../{scangrp}/{scan_id}/{frame:03d}/{scan_id}{frame:03d}-w{band}-int-1b.fits
Fatal mask bits (0-4, 9, 10-18: bad, broken, saturated) are already NaN in the int image,
so the gzipped msk file is not needed for stamps.
"""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS

UA = {"User-Agent": "planet-x-spherex-probe"}
SIA = "https://irsa.ipac.caltech.edu/SIA"
BUCKET_URL = "https://nasa-irsa-wise.s3.amazonaws.com/"
COLLECTIONS = ("wise_allsky", "wise_3bandcryo", "wise_2bandcryo", "neowiser")
BANDS = {"W1": 1, "W2": 2}
HEADER_GUESS = 40960  # L1b int headers are 13 blocks (37440 B); refetch if longer
# IBE access_url prefix -> bucket prefix. (SIA's CSV cloud_access JSON is not quoted, so its
# commas split the field; we map the IBE URL instead.)
IBE_TO_BUCKET = {
    "https://irsa.ipac.caltech.edu/ibe/data/wise/allsky/4band_p1bm_frm/": "wise/allsky/images/4band_p1bm_frm/",
    "https://irsa.ipac.caltech.edu/ibe/data/wise/cryo_3band/3band_p1bm_frm/": "wise/cryo-3band/images/3band_p1bm_frm/",
    "https://irsa.ipac.caltech.edu/ibe/data/wise/postcryo/2band_p1bm_frm/": "wise/postcryo/images/2band_p1bm_frm/",
    "https://irsa.ipac.caltech.edu/ibe/data/wise/neowiser/p1bm_frm/": "wise/neowiser/images/p1bm_frm/",
}

_session = requests.Session()
_session.headers.update(UA)
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32))


@dataclass(frozen=True)
class Frame:
    key: str          # object key in s3://nasa-irsa-wise
    band: int         # 1 or 2
    mjd: float
    obs_id: str


@dataclass(frozen=True)
class Stamp:
    frame: Frame
    data: np.ndarray  # float32 rows y0..y1 of the frame, full width
    wcs: WCS          # WCS of `data` (SIP included)
    header: fits.Header
    nbytes: int       # bytes transferred


def _sia(collection: str, ra: float, dec: float) -> list[Frame]:
    r = _session.get(SIA, params={"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} 0.002",
                                  "RESPONSEFORMAT": "CSV"}, timeout=120)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        band = BANDS.get(row["energy_bandpassname"])
        if row["dataproduct_subtype"] != "science" or band is None:
            continue
        url = row["access_url"]
        if not url.endswith("-int-1b.fits"):  # SIA also returns Atlas coadd tiles (p3am_cdd)
            continue
        prefix = next((k for k in IBE_TO_BUCKET if url.startswith(k)), None)
        if prefix is None:
            raise ValueError(f"unknown WISE access_url prefix: {url}")
        key = IBE_TO_BUCKET[prefix] + url[len(prefix):]
        out.append(Frame(key=key, band=band, mjd=float(row["t_min"]), obs_id=row["obs_id"]))
    return out


def find_frames(ra: float, dec: float) -> list[Frame]:
    """All W1/W2 int frames whose footprint contains (ra, dec), all four mission phases."""
    with ThreadPoolExecutor(len(COLLECTIONS)) as ex:
        parts = ex.map(lambda c: _sia(c, ra, dec), COLLECTIONS)
    return sorted((f for p in parts for f in p), key=lambda f: f.mjd)


def _get_range(key: str, start: int, stop: int) -> bytes:
    r = _session.get(BUCKET_URL + key, headers={"Range": f"bytes={start}-{stop - 1}"}, timeout=60)
    r.raise_for_status()
    return r.content


def _find_end(raw: bytes) -> int:
    """Byte offset of the END card, scanning card-aligned (80 B); -1 if not yet read."""
    for i in range(0, len(raw) - 79, 80):
        if raw[i:i + 3] == b"END" and raw[i + 3:i + 80].strip() == b"":
            return i
    return -1


def _read_header(key: str) -> tuple[fits.Header, int, int]:
    raw = _get_range(key, 0, HEADER_GUESS)
    end = _find_end(raw)
    while end < 0:
        more = _get_range(key, len(raw), len(raw) + HEADER_GUESS)
        if not more:
            raise ValueError(f"no END card in {key}")
        raw += more
        end = _find_end(raw)
    data_start = (end // 2880 + 1) * 2880
    return fits.Header.fromstring(raw[:end + 80].decode("ascii")), data_start, len(raw)


def read_stamp(frame: Frame, ra: float, dec: float, radius_pix: int) -> Stamp | None:
    """Range-read the full-width rows within radius_pix of (ra, dec). None if off-frame."""
    hdr, data_start, nb = _read_header(frame.key)
    nx, ny = hdr["NAXIS1"], hdr["NAXIS2"]
    w = WCS(hdr)
    x, y = w.world_to_pixel_values(ra, dec)
    if not (-radius_pix < x < nx + radius_pix and -radius_pix < y < ny + radius_pix):
        return None
    y0, y1 = max(int(y) - radius_pix, 0), min(int(y) + radius_pix + 1, ny)
    if y1 <= y0:
        return None
    row = nx * 4  # BITPIX -32
    raw = _get_range(frame.key, data_start + y0 * row, data_start + y1 * row)
    data = np.frombuffer(raw, dtype=">f4").reshape(y1 - y0, nx).astype(np.float32)
    return Stamp(frame=frame, data=data, wcs=w.slice((slice(y0, y1), slice(None))),
                 header=hdr, nbytes=nb + len(raw))
