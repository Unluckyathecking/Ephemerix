"""Row format of the SPHEREx frame index, and the parser that fills it from file headers.

One row per Level-2 file in the public bucket. A row is built from the first few tens of KB
of the file (the primary header and the IMAGE header); no pixel data is read.
"""

from __future__ import annotations

import math
import re
import warnings
from typing import Any

import numpy as np
import pyarrow as pa
from astropy.io import fits
from astropy.wcs import WCS

from .indexwcs import WcsTable, sip_terms, sky_to_pixel

SCHEMA_VERSION = 1
HEADER_RANGE_BYTES = 32768  # first request; headers ended at 25920 or 28800 B in 240 samples
RADIUS_PAD_DEG = 0.01  # bounding radius slack beyond the sampled boundary

# Full wavelength range of each detector in metres, as IRSA's SIA reports it (em_min, em_max).
DETECTOR_BAND_M: dict[int, tuple[float, float]] = {
    1: (7.455e-07, 1.1167e-06), 2: (1.1033e-06, 1.6499e-06), 3: (1.6301e-06, 2.4346e-06),
    4: (2.4027e-06, 3.8473e-06), 5: (3.8113e-06, 4.43e-06), 6: (4.4115e-06, 5.0096e-06),
}

_KEY_RE = re.compile(
    r"^(?P<release>[a-z0-9]+)/level2/(?P<week>[^/]+)/(?P<pipeline>[^/]+)/(?P<det>[1-6])/"
    r"level2_(?P<obs>.+)D(?P=det)_spx_(?P=pipeline)\.fits$")
_WCS_KEYS = re.compile(
    r"^(NAXIS[12]?|WCSAXES|CRPIX[12]|CRVAL[12]|PC[12]_[12]|CD[12]_[12]|CDELT[12]|CTYPE[12]|"
    r"CUNIT[12]|LONPOLE|LATPOLE|RADESYS|A_ORDER|B_ORDER|A_\d+_\d+|B_\d+_\d+)$")

SCHEMA = pa.schema([
    ("key", pa.string()), ("release", pa.string()), ("week", pa.string()),
    ("pipeline", pa.string()), ("obs_id", pa.string()), ("detector", pa.int8()),
    ("expidn", pa.int64()), ("sps_flags", pa.string()),
    ("mjd", pa.float64()), ("xposure_s", pa.float32()),
    ("naxis1", pa.int16()), ("naxis2", pa.int16()),
    ("crval1", pa.float64()), ("crval2", pa.float64()),
    ("crpix1", pa.float32()), ("crpix2", pa.float32()),
    ("cd11", pa.float32()), ("cd12", pa.float32()), ("cd21", pa.float32()),
    ("cd22", pa.float32()),
    ("sip_order", pa.int8()), ("sip_ap", pa.list_(pa.float32())),
    ("sip_bp", pa.list_(pa.float32())),
    ("ra_c", pa.float64()), ("dec_c", pa.float64()),
    ("ra1", pa.float64()), ("dec1", pa.float64()), ("ra2", pa.float64()),
    ("dec2", pa.float64()), ("ra3", pa.float64()), ("dec3", pa.float64()),
    ("ra4", pa.float64()), ("dec4", pa.float64()),
    ("radius_deg", pa.float32()), ("inv_err_px", pa.float32()), ("size_bytes", pa.int64()),
])


class UnreadableFrame(ValueError):
    """A file whose headers cannot be turned into an index row."""


class HeaderTruncated(UnreadableFrame):
    """The bytes given end before the IMAGE header does; fetch more and retry."""


def split_key(key: str) -> dict[str, str]:
    """release, week, pipeline, det and obs (as in the file name) of a Level-2 key."""
    m = _KEY_RE.match(key)
    if not m:
        raise UnreadableFrame(f"unexpected key layout: {key}")
    return m.groupdict()


def rebuild_key(release: str, week: str, pipeline: str, obs_id: str, detector: int) -> str:
    """Inverse of split_key: the bucket key of a frame."""
    return (f"{release}/level2/{week}/{pipeline}/{detector}/"
            f"level2_{obs_id}D{detector}_spx_{pipeline}.fits")


def header_end(data: bytes, start: int = 0) -> int:
    """Offset just past the END card of the FITS header beginning at `start`."""
    pos = start
    while True:
        i = data.find(b"END     ", pos)
        if i < 0:
            raise HeaderTruncated(f"no END card in {len(data)} bytes")
        if (i - start) % 80 == 0 and data[i:i + 80].strip() == b"END":
            return start + -(-(i - start + 80) // 2880) * 2880
        pos = i + 1


def image_header(data: bytes) -> fits.Header:
    """The IMAGE extension header from the leading bytes of a Level-2 file."""
    if not data.startswith(b"SIMPLE"):
        raise UnreadableFrame("not a FITS file")
    p_end = header_end(data)
    i_end = header_end(data, p_end)
    return fits.Header.fromstring(data[p_end:i_end].decode("ascii"))


def _wcs_table(hdr: fits.Header) -> tuple[WcsTable, dict[str, Any]]:
    """Inverse-WCS parameters from the header, plus the pieces the row stores."""
    for k in (1, 2):
        ctype = str(hdr.get(f"CTYPE{k}", ""))
        if not ctype.endswith("TAN-SIP") and not ctype.endswith("TAN"):
            raise UnreadableFrame(f"unsupported CTYPE{k} {ctype!r}")
    if str(hdr.get("RADESYS", "ICRS")).strip() != "ICRS":
        raise UnreadableFrame("RADESYS is not ICRS")
    if float(hdr.get("LONPOLE", 180.0)) != 180.0:
        raise UnreadableFrame("LONPOLE is not 180")
    if "CD1_1" in hdr:
        cd = [float(hdr[f"CD{i}_{j}"]) for i in (1, 2) for j in (1, 2)]
    else:
        cd = [float(hdr.get(f"PC{i}_{j}", 1.0 if i == j else 0.0)) * float(hdr.get(f"CDELT{i}", 1.0))
              for i in (1, 2) for j in (1, 2)]
    order = int(hdr.get("AP_ORDER", 0))
    if int(hdr.get("A_ORDER", 0)) and not order:
        raise UnreadableFrame("SIP without inverse (AP/BP) coefficients")
    if order != int(hdr.get("BP_ORDER", 0)):
        raise UnreadableFrame("AP_ORDER and BP_ORDER differ")
    ap = [float(hdr.get(f"AP_{p}_{q}", 0.0)) for p, q in sip_terms(order)]
    bp = [float(hdr.get(f"BP_{p}_{q}", 0.0)) for p, q in sip_terms(order)]
    one = lambda v: np.array([v], dtype=float)
    table = WcsTable(
        one(hdr["CRVAL1"]), one(hdr["CRVAL2"]), one(hdr["CRPIX1"]), one(hdr["CRPIX2"]),
        one(cd[0]), one(cd[1]), one(cd[2]), one(cd[3]),
        np.array([ap], dtype=float), np.array([bp], dtype=float), order)
    return table, {"cd": cd, "order": order, "ap": ap, "bp": bp}


def _footprint(hdr: fits.Header, n1: int, n2: int) -> tuple[np.ndarray, np.ndarray]:
    """Sky positions (deg) of the centre, 4 corners and 4 edge midpoints, with full SIP."""
    keep = fits.Header([c for c in hdr.cards if _WCS_KEYS.match(c.keyword)])
    keep["WCSAXES"] = 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wcs = WCS(keep)
        xs = np.array([(n1 + 1) / 2, 0.5, n1 + 0.5, n1 + 0.5, 0.5,
                       (n1 + 1) / 2, n1 + 0.5, (n1 + 1) / 2, 0.5])
        ys = np.array([(n2 + 1) / 2, 0.5, 0.5, n2 + 0.5, n2 + 0.5,
                       0.5, (n2 + 1) / 2, n2 + 0.5, (n2 + 1) / 2])
        ra, dec = wcs.all_pix2world(xs, ys, 1)
    return np.asarray(ra) % 360.0, np.asarray(dec)


def _sep_deg(ra0: float, dec0: float, ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    """Angular separation in degrees (haversine)."""
    r0, d0, r, d = map(np.radians, (ra0, dec0, ra, dec))
    h = np.sin((d - d0) / 2) ** 2 + np.cos(d0) * np.cos(d) * np.sin((r - r0) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1))))


def parse_frame(key: str, size: int, data: bytes) -> dict[str, Any]:
    """Index row (a dict matching SCHEMA) for the file `key` from its leading bytes.

    Raises HeaderTruncated if `data` is too short, UnreadableFrame for anything else wrong.
    """
    parts = split_key(key)
    try:
        hdr = image_header(data)
        return _row(key, size, parts, hdr)
    except UnreadableFrame:
        raise
    except (KeyError, ValueError, TypeError, UnicodeDecodeError) as e:
        raise UnreadableFrame(f"{type(e).__name__}: {e}") from e


def _row(key: str, size: int, parts: dict[str, str], hdr: fits.Header) -> dict[str, Any]:
    n1, n2 = int(hdr["NAXIS1"]), int(hdr["NAXIS2"])
    det = int(hdr["DETECTOR"])
    obs_id = str(hdr["OBSID"]).strip()
    if det != int(parts["det"]) or f"{obs_id}" != parts["obs"]:
        raise UnreadableFrame(f"header disagrees with key: DETECTOR={det} OBSID={obs_id}")
    mjd = 0.5 * (float(hdr["MJD-BEG"]) + float(hdr["MJD-END"]))
    table, w = _wcs_table(hdr)
    ra, dec = _footprint(hdr, n1, n2)
    if not (np.all(np.isfinite(ra)) and np.all(np.isfinite(dec))):
        raise UnreadableFrame("non-finite footprint")
    radius = float(_sep_deg(ra[0], dec[0], ra[1:], dec[1:]).max()) + RADIUS_PAD_DEG
    if not 0.0 < radius < 10.0:
        raise UnreadableFrame(f"implausible footprint radius {radius:.3f} deg")
    xs = np.array([(n1 + 1) / 2, 0.5, n1 + 0.5, n1 + 0.5, 0.5])
    ys = np.array([(n2 + 1) / 2, 0.5, 0.5, n2 + 0.5, n2 + 0.5])
    x, y, ok = sky_to_pixel(ra[:5], dec[:5], _tile(table, 5))
    inv_err = float(np.nanmax(np.hypot(x - xs, y - ys))) if ok.all() else math.inf
    row: dict[str, Any] = {
        "key": key, "release": parts["release"], "week": parts["week"],
        "pipeline": parts["pipeline"], "obs_id": obs_id, "detector": det,
        "expidn": int(hdr.get("EXPIDN", 0)), "sps_flags": str(hdr.get("SPS_FLAGS", "")).strip(),
        "mjd": mjd, "xposure_s": float(hdr.get("XPOSURE", float("nan"))),
        "naxis1": n1, "naxis2": n2, "crval1": float(hdr["CRVAL1"]),
        "crval2": float(hdr["CRVAL2"]), "crpix1": float(hdr["CRPIX1"]),
        "crpix2": float(hdr["CRPIX2"]), "cd11": w["cd"][0], "cd12": w["cd"][1],
        "cd21": w["cd"][2], "cd22": w["cd"][3], "sip_order": w["order"],
        "sip_ap": w["ap"], "sip_bp": w["bp"], "ra_c": float(ra[0]), "dec_c": float(dec[0]),
        "radius_deg": radius, "inv_err_px": inv_err, "size_bytes": size,
    }
    for i in range(4):
        row[f"ra{i + 1}"], row[f"dec{i + 1}"] = float(ra[i + 1]), float(dec[i + 1])
    if inv_err > 0.5:
        raise UnreadableFrame(f"inverse WCS disagrees with astropy by {inv_err:.2f} px")
    return row


def _tile(t: WcsTable, n: int) -> WcsTable:
    """The one-row table `t` repeated n times."""
    return t.take(np.zeros(n, dtype=int))


def rows_to_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Arrow table in SCHEMA order from parsed rows."""
    return pa.Table.from_pylist(rows, schema=SCHEMA)

