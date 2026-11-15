"""Read a small stamp from one SPHEREx Level-2 file without downloading it.

File layout (DR1/QR3, pipeline l2b-v27): 0 PRIMARY, 1 IMAGE f32 MJy/sr (zodi not
subtracted, TAN-SIP), 2 FLAGS int32 RICE_1 tiled one row per tile, 3 VARIANCE f32
(MJy/sr)^2, 4 ZODI f32 MJy/sr, 5 EPSF table (33x33 PSFs oversampled x5 on a grid that
differs per detector), 6 WCS-WAVE table (9x9 wavelength and bandwidth control points).

The headers are walked once with astropy; uncompressed image rows and EPSF rows are then
read directly from their byte offsets (dtype from BITPIX), FLAGS through astropy's
public `section`. With prefetch=True all those byte ranges are fetched in two parallel
batches first; the decoding is identical either way.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

from . import config
from .fitsfile import RangeFile
from .net import BlockStore

log = logging.getLogger(__name__)

_BITPIX = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}
_PLANES = ("IMAGE", "VARIANCE", "ZODI")


@dataclass(frozen=True)
class Stamp:
    """Square cutout of one frame. Arrays are read-only, NaN (FLAGS MISSING_DATA) off-detector.

    x0, y0: 0-based full-frame column and row of stamp[0, 0]. xpix, ypix: 0-based
    full-frame position of the requested sky position. wave_um, band_um: central
    wavelength and bandwidth there (from WCS-WAVE). psf: 33x33 EPSF oversampled x5 for
    that position, or None.
    """

    key: str
    image: np.ndarray
    flags: np.ndarray
    variance: np.ndarray
    zodi: np.ndarray
    x0: int
    y0: int
    xpix: float
    ypix: float
    wave_um: float
    band_um: float
    mjd: float
    detector: int
    header: str
    psf: np.ndarray | None = None
    wave_table: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None  # WCS-WAVE X, Y, VALUES
    # The stamp's WCS, built on first use: parsing the full header with SIP costs several ms
    # and the stack, the window selection and the photometry each asked for it again.
    # Not an init field, so dataclasses.replace() never carries a stale one over.
    _wcs: WCS | None = field(default=None, init=False, repr=False, compare=False)

    def wave_at_pixel(self, x: float, y: float) -> tuple[float, float]:
        """(wavelength, bandwidth) in um at a 0-based full-frame pixel."""
        if self.wave_table is None:
            raise ValueError("stamp has no WCS-WAVE table")
        xs, ys, v = self.wave_table
        return wave_at({"X": xs, "Y": ys, "VALUES": v}, x, y)

    def pixel_of(self, ra: float, dec: float) -> tuple[float, float]:
        """0-based full-frame pixel (x, y) of a sky position in degrees."""
        sx, sy = self.wcs().world_to_pixel_values(ra, dec)
        return float(sx) + self.x0, float(sy) + self.y0

    def wcs(self) -> WCS:
        """WCS of the stamp array (the frame's TAN-SIP WCS with CRPIX shifted by x0, y0).

        Built once per stamp and shared by the callers; treat it as read-only."""
        if self._wcs is None:
            h = fits.Header.fromstring(self.header)
            h["CRPIX1"] = h["CRPIX1"] - self.x0
            h["CRPIX2"] = h["CRPIX2"] - self.y0
            object.__setattr__(self, "_wcs", _wcs(h))
        return self._wcs


def _wcs(header: fits.Header) -> WCS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(header, naxis=2)


def wave_at(row: Mapping[str, Any] | np.void, x: float, y: float) -> tuple[float, float]:
    """Bilinear (wavelength, bandwidth) in um at 0-based pixel (x, y) from a WCS-WAVE row.

    VALUES is indexed [iy, ix, (wave, band)] on 1-based control points X, Y. Do not use
    astropy WCS(key='W'): it applies the image SIP terms too and is off by 0.4-8 nm.
    """
    xs = np.asarray(row["X"], float)
    ys = np.asarray(row["Y"], float)
    v = np.asarray(row["VALUES"], float)
    xb, yb = x + 1.0, y + 1.0
    ix = int(np.clip(np.searchsorted(xs, xb) - 1, 0, len(xs) - 2))
    iy = int(np.clip(np.searchsorted(ys, yb) - 1, 0, len(ys) - 2))
    tx = (xb - xs[ix]) / (xs[ix + 1] - xs[ix])
    ty = (yb - ys[iy]) / (ys[iy + 1] - ys[iy])
    out = ((1 - tx) * (1 - ty) * v[iy, ix] + tx * (1 - ty) * v[iy, ix + 1]
           + (1 - tx) * ty * v[iy + 1, ix] + tx * ty * v[iy + 1, ix + 1])
    return float(out[0]), float(out[1])


def _plane_range(hdu: fits.ImageHDU, ya: int, yb: int) -> tuple[int, int]:
    """Byte range [start, end) of full rows ya..yb-1 of an uncompressed image HDU."""
    h = hdu.header
    rowbytes = h["NAXIS1"] * abs(h["BITPIX"]) // 8
    loc = hdu.fileinfo()["datLoc"]
    return loc + ya * rowbytes, loc + yb * rowbytes


def _read_plane(store: BlockStore, key: str, hdu: fits.ImageHDU, ya: int, yb: int) -> np.ndarray:
    h = hdu.header
    a, b = _plane_range(hdu, ya, yb)
    rows = np.frombuffer(store.read(key, a, b), dtype=_BITPIX[h["BITPIX"]]).reshape(yb - ya, -1)
    out = rows.astype(np.float32) if h["BITPIX"] < 0 else rows.astype(np.float64)
    if "BSCALE" in h or "BZERO" in h:
        out = out * h.get("BSCALE", 1.0) + h.get("BZERO", 0.0)
    return out


def _flags_ranges(store: BlockStore, key: str, hdu: fits.CompImageHDU,
                  ya: int, yb: int) -> list[tuple[int, int]]:
    """Byte ranges of the compressed FLAGS tiles for rows ya..yb-1 (row tiles only).

    Parses the table's own header and descriptors per the FITS standard; returns [] when
    the layout is not one tile per row, in which case astropy simply reads on demand.
    """
    info = hdu.fileinfo()
    th = fits.Header.fromstring(store.read(key, info["hdrLoc"], info["datLoc"]).decode("ascii"))
    tform = th.get("TFORM1", "")
    if th.get("ZTILE2", 0) != 1 or th.get("TTYPE1") != "COMPRESSED_DATA" or tform[:2] not in (
            "1P", "1Q"):
        return []
    rowlen, loc = th["NAXIS1"], info["datLoc"]
    table = (loc, loc + rowlen * th["NAXIS2"])
    desc = np.frombuffer(store.read(key, loc + ya * rowlen, loc + yb * rowlen), dtype=np.uint8)
    desc = desc.reshape(yb - ya, rowlen)[:, :8 if tform[1] == "P" else 16]
    pairs = desc.copy().view(">i4" if tform[1] == "P" else ">i8").reshape(yb - ya, 2)
    heap = loc + th.get("THEAP", rowlen * th["NAXIS2"])
    start = heap + int(pairs[:, 1].min())
    end = heap + int((pairs[:, 1] + pairs[:, 0]).max())  # 'B' elements are 1 byte
    return [table, (start, end)]


def _pad(rows: np.ndarray, xa: int, x0: int, size: int, ya: int, y0: int, fill: float) -> np.ndarray:
    out = np.full((size, size), fill, dtype=rows.dtype)
    out[ya - y0:ya - y0 + rows.shape[0], xa - x0:xa - x0 + rows.shape[1]] = rows
    return out


def _read_epsf(store: BlockStore, key: str, hdu: fits.BinTableHDU, n: int,
               x: float, y: float) -> np.ndarray:
    """The EPSF row for the PSF bin containing 0-based (x, y); bin widths come from row 0."""
    rowlen = hdu.header["NAXIS1"]
    loc = hdu.fileinfo()["datLoc"]
    dtype = hdu.columns.dtype.newbyteorder(">")

    def row(i: int) -> np.void:
        return np.frombuffer(store.read(key, loc + i * rowlen, loc + (i + 1) * rowlen), dtype)[0]

    first = row(0)
    nx = round(n / float(first["XWIDTH"]))
    bx = min(int(x / float(first["XWIDTH"])), nx - 1)
    by = int(y / float(first["YWIDTH"]))
    rec = row(by * nx + bx)
    if int(rec["BINX"]) != bx or int(rec["BINY"]) != by:
        raise ValueError(f"EPSF row order unexpected: got bin {rec['BINX']},{rec['BINY']}")
    psf = np.asarray(rec["EPSF"], float).reshape(config.EPSF_SIZE, config.EPSF_SIZE)
    return psf


@dataclass(frozen=True)
class Request:
    """One stamp wanted from a frame: centre (ra, dec) deg, half-size px, with the EPSF?"""

    ra: float
    dec: float
    half: int = config.STAMP_HALF
    with_psf: bool = True


@dataclass(frozen=True)
class _Window:
    x: float
    y: float
    x0: int
    y0: int
    ya: int
    yb: int
    xa: int
    xb: int
    size: int


def _window(hdr: fits.Header, req: Request) -> _Window | None:
    x, y = (float(v) for v in _wcs(hdr).world_to_pixel_values(req.ra, req.dec))
    n = int(hdr["NAXIS1"])
    if not (0 <= x < n and 0 <= y < int(hdr["NAXIS2"])):
        return None
    size = 2 * req.half + 1
    x0, y0 = round(x) - req.half, round(y) - req.half
    return _Window(x, y, x0, y0, max(y0, 0), min(y0 + size, n), max(x0, 0), min(x0 + size, n),
                   size)


def _ranges(store: BlockStore, key: str, h: fits.HDUList, wins: list[_Window],
            with_psf: bool) -> list[tuple[int, int]]:
    """Every byte range the stamps in `wins` need, for one parallel prefetch."""
    out = []
    for w in wins:
        out += [_plane_range(h[p], w.ya, w.yb) for p in _PLANES]
        out += _flags_ranges(store, key, h["FLAGS"], w.ya, w.yb)
    if with_psf:
        loc = h["EPSF"].fileinfo()["datLoc"]
        out.append((loc, loc + h["EPSF"].header["NAXIS1"]))
    return out


def _cut(store: BlockStore, key: str, h: fits.HDUList, w: _Window, with_psf: bool,
         wrow: np.void, table: tuple[np.ndarray, ...]) -> Stamp:
    hdr = h["IMAGE"].header
    planes = {p: _pad(_read_plane(store, key, h[p], w.ya, w.yb)[:, w.xa:w.xb], w.xa, w.x0,
                      w.size, w.ya, w.y0, np.nan) for p in _PLANES}
    flags = _pad(np.asarray(h["FLAGS"].section[w.ya:w.yb, w.xa:w.xb], dtype=np.int32), w.xa,
                 w.x0, w.size, w.ya, w.y0, config.MISSING_MASK)
    wave, band = wave_at(wrow, w.x, w.y)
    psf = _read_epsf(store, key, h["EPSF"], int(hdr["NAXIS1"]), w.x, w.y) if with_psf else None
    arrays = [planes["IMAGE"], flags, planes["VARIANCE"], planes["ZODI"]]
    for a in arrays + ([psf] if psf is not None else []):
        a.setflags(write=False)
    return Stamp(key, *arrays, x0=w.x0, y0=w.y0, xpix=w.x, ypix=w.y, wave_um=wave, band_um=band,
                 mjd=float(hdr["MJD-AVG"]), detector=int(hdr["DETECTOR"]),
                 header=hdr.tostring(), psf=psf, wave_table=table)


def read_stamps(store: BlockStore, key: str, requests: list[Request],
                prefetch: bool = True) -> list[Stamp | None]:
    """One stamp per request (None where its position is off the detector), from a single
    pass over the file: the headers are walked once and the byte ranges of every stamp are
    prefetched in one parallel batch. Each stamp is identical to what `read_stamp` gives."""
    with fits.open(RangeFile(store, key), lazy_load_hdus=True, memmap=False) as h:
        h.readall()
        hdr = h["IMAGE"].header
        wins = [_window(hdr, r) for r in requests]
        on = [(w, r) for w, r in zip(wins, requests) if w is not None]
        if not on:
            return [None] * len(requests)
        if prefetch:
            store.prefetch(key, _ranges(store, key, h, [w for w, _ in on],
                                        any(r.with_psf for _, r in on)))
        wrow = h["WCS-WAVE"].data[0]
        table = tuple(np.array(wrow[c], float) for c in ("X", "Y", "VALUES"))
        return [None if w is None else _cut(store, key, h, w, r.with_psf, wrow, table)
                for w, r in zip(wins, requests)]


def read_stamp(store: BlockStore, key: str, ra: float, dec: float, half: int = config.STAMP_HALF,
               with_psf: bool = True, prefetch: bool = True) -> Stamp | None:
    """Stamp of (2*half+1)^2 px centred on (ra, dec) deg, or None if that is off the detector."""
    return read_stamps(store, key, [Request(ra, dec, half, with_psf)], prefetch)[0]
