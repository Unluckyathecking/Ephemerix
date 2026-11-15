"""Read a small stamp from one SPHEREx Level-2 frame on S3 without downloading it.

Layout of a DR1/QR3 L2 file (checked 14 Nov 2026, pipeline l2b-v27):
  0 PRIMARY, 1 IMAGE f32 (MJy/sr, zodi NOT subtracted), 2 FLAGS int32 RICE_1 tiled
  2040x1 (one row per tile), 3 VARIANCE f32, 4 ZODI f32, 5 EPSF bintable 441 rows
  (21x21 grid, 33x33 PSF oversampled x5), 6 WCS-WAVE bintable (9x9 grid, wave+band).

Only the headers, the needed rows of each image and the 720-byte WCS-WAVE table
are fetched. The backend can lift `read_stamp` and `wave_at` as they are.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import fsspec
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

BUCKET = "nasa-irsa-spherex"
IBE_PREFIX = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"
BLOCK = 288 * 1024  # one block covers 31 rows x 8160 B, so each image section is one GET

# FLAGS bits that make a pixel unusable for photometry (names from the FLAGS header).
BAD_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "NONFUNC": 6, "MISSING_DATA": 9,
    "HOT": 10, "COLD": 11, "NONLINEAR": 15, "PERSIST": 17, "OUTLIER": 19,
}
BAD_MASK = sum(1 << b for b in BAD_BITS.values())


def s3_key_from_url(url: str) -> str:
    """IRSA IBE access_url -> key in the public bucket (same path)."""
    return url.split(IBE_PREFIX, 1)[1]


@dataclass(frozen=True)
class Stamp:
    image: np.ndarray      # MJy/sr
    flags: np.ndarray      # int32 bitmask
    variance: np.ndarray   # (MJy/sr)^2
    zodi: np.ndarray       # MJy/sr
    x0: int                # 0-based column of stamp[0, 0] in the full frame
    y0: int
    xpix: float            # 0-based target position in the full frame
    ypix: float
    wave_um: float         # central wavelength at the target pixel
    band_um: float         # bandwidth at the target pixel
    mjd: float
    detector: int
    header: fits.Header    # IMAGE header
    bytes_read: int
    psf: tuple | None = None  # (33x33 EPSF oversampled x5, CWAVE, CBAND) if requested


class _CountingFile:
    """Wrap an fsspec file to count bytes actually fetched from S3."""

    def __init__(self, f):
        self._f = f
        self.nbytes = 0
        orig = f._fetch_range

        def counted(start, end):
            data = orig(start, end)
            self.nbytes += len(data)
            return data

        f._fetch_range = counted
        f.cache.fetcher = counted

    def __getattr__(self, name):
        return getattr(self._f, name)


def wave_at(table_row, x0b: float, y0b: float) -> tuple[float, float]:
    """Bilinear lookup of (wavelength, bandwidth) in um at 0-based pixel (x, y).

    WCS-WAVE VALUES is indexed [iy, ix, (wave, band)] on 1-based control points X, Y.
    Do not use astropy WCS(key='W') on the IMAGE header: it also applies the SIP
    terms and is off by 0.4-8 nm across the detector (up to ~20% of a channel).
    """
    xs = np.asarray(table_row["X"], float)
    ys = np.asarray(table_row["Y"], float)
    v = np.asarray(table_row["VALUES"], float)
    x, y = x0b + 1.0, y0b + 1.0
    ix = int(np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2))
    iy = int(np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2))
    tx = (x - xs[ix]) / (xs[ix + 1] - xs[ix])
    ty = (y - ys[iy]) / (ys[iy + 1] - ys[iy])
    out = ((1 - tx) * (1 - ty) * v[iy, ix] + tx * (1 - ty) * v[iy, ix + 1]
           + (1 - tx) * ty * v[iy + 1, ix] + tx * ty * v[iy + 1, ix + 1])
    return float(out[0]), float(out[1])


def _section(hdu, y0: int, x0: int, size: int, n: int, fill):
    """Read hdu[y0:y0+size, x0:x0+size], padding outside the detector with `fill`."""
    out = np.full((size, size), fill, dtype=hdu.section[0:1, 0:1].dtype)
    ya, yb, xa, xb = max(y0, 0), min(y0 + size, n), max(x0, 0), min(x0 + size, n)
    if ya < yb and xa < xb:
        out[ya - y0:yb - y0, xa - x0:xb - x0] = hdu.section[ya:yb, xa:xb]
    return out


def read_epsf_row(f, h, x: float, y: float) -> tuple[np.ndarray, float, float]:
    """Fetch only the EPSF row (8752 B) for the PSF bin containing 0-based (x, y).

    The grid differs by detector (21x21 on D1, 11x41 on D3, ...), so the bin widths
    are read from the first row (XWIDTH/YWIDTH); rows are ordered x-fast then y.
    """
    hdu = h["EPSF"]
    n = h["IMAGE"].header["NAXIS1"]
    rowlen = hdu.header["NAXIS1"]
    dtype = hdu.columns.dtype.newbyteorder(">")

    def row(i: int):
        f.seek(hdu._data_offset + i * rowlen)
        return np.frombuffer(f.read(rowlen), dtype=dtype)[0]

    first = row(0)
    nx = int(round(n / float(first["XWIDTH"])))
    bx = min(int(x / float(first["XWIDTH"])), nx - 1)
    by = int(y / float(first["YWIDTH"]))
    rec = row(by * nx + bx)
    assert rec["BINX"] == bx and rec["BINY"] == by, (rec["BINX"], rec["BINY"], bx, by)
    psf = np.asarray(rec["EPSF"], float).reshape(33, 33)
    return psf, float(rec["CWAVE"]), float(rec["CBAND"])


def read_stamp(key: str, ra: float, dec: float, half: int = 15, psf: bool = False) -> Stamp:
    """Fetch a (2*half+1)^2 stamp of IMAGE/FLAGS/VARIANCE/ZODI centred on (ra, dec).

    Pixels off the detector come back NaN (FLAGS = MISSING_DATA). With psf=True the
    EPSF for the target's bin is fetched too (two 8.7 kB rows) into Stamp.psf.
    """
    fs = fsspec.filesystem("s3", anon=True)
    size = 2 * half + 1
    with fs.open(f"{BUCKET}/{key}", "rb", block_size=BLOCK, cache_type="readahead") as raw:
        f = _CountingFile(raw)
        with fits.open(f, lazy_load_hdus=True, memmap=False) as h:
            hdr = h["IMAGE"].header
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FITSFixedWarning)
                w = WCS(hdr)
            x, y = (float(v) for v in w.world_to_pixel_values(ra, dec))
            n = hdr["NAXIS1"]
            x0, y0 = int(round(x)) - half, int(round(y)) - half
            image = _section(h["IMAGE"], y0, x0, size, n, np.nan)
            flags = _section(h["FLAGS"], y0, x0, size, n, 1 << 9)
            variance = _section(h["VARIANCE"], y0, x0, size, n, np.nan)
            zodi = _section(h["ZODI"], y0, x0, size, n, np.nan)
            wave, band = wave_at(h["WCS-WAVE"].data[0], x, y)
            epsf = read_epsf_row(raw, h, x, y) if psf and 0 <= x < n and 0 <= y < n else None
            return Stamp(image, flags.astype(np.int32), variance, zodi, x0, y0, x, y, wave, band,
                         float(hdr["MJD-AVG"]), int(hdr["DETECTOR"]), hdr, f.nbytes, epsf)
