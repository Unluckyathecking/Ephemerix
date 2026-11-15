"""Range-read the part of an L1b int frame that a grid needs: two GETs per frame.

1. The header (first 40 kB; extended if the END card is further on), for the WCS with SIP.
2. One contiguous byte range: the full-width rows spanning the grid's footprint on the frame.
   S3 allows one range per request, so a full-width strip is the minimum.
Saturated and other fatal-mask pixels are already NaN in the int image (WISE Explanatory
Supplement sec. 4.4a), so the gzipped mask file is not read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from pxs.grid import Grid
from pxs.wise import net
from pxs.wise.frames import Frame
from pxs.wise.geometry import grid_border

HEADER_GUESS = 40960  # L1b int headers are 13 FITS blocks (37,440 B)
ROW_PAD = 3  # extra rows each side, for interpolation at the grid edge
CARD = 80
BLOCK = 2880

RangeFetch = Callable[[str, int, int], bytes]


@dataclass(frozen=True)
class Exposure:
    """A strip of full-width rows ``y0 .. y0 + data.shape[0]`` of a frame, in DN.

    ``wcs`` maps strip pixels to the sky (SIP included); ``full_shape`` is the frame's
    (ny, nx); ``header`` holds the primary header's WCS and image-shape cards
    (``WCS_KEYWORDS``), which is all the pipeline uses.
    """

    frame: Frame
    data: np.ndarray
    wcs: WCS
    y0: int
    full_shape: tuple[int, int]
    header: fits.Header


def _end_card(raw: bytes) -> int:
    """Offset of the END card scanning 80-byte cards, or -1 if not read yet."""
    for i in range(0, len(raw) - CARD + 1, CARD):
        if raw[i:i + 3] == b"END" and raw[i + 3:i + CARD].strip() == b"":
            return i
    return -1


# Cards a frame's WCS (with SIP) and its image shape are built from. An L1b header has about
# 450 cards; parsing and verifying all of them took most of the per-frame CPU of a read,
# while a WCS from these ~85 gives bit-identical transforms (tests/wise/test_wise_reader.py).
WCS_KEYWORDS = ("SIMPLE", "BITPIX", "NAXIS", "CTYPE", "CRVAL", "CRPIX", "CD1_", "CD2_",
                "CDELT", "PC1_", "PC2_", "CROTA", "CUNIT", "A_", "B_", "AP_", "BP_", "PV1_",
                "PV2_", "RADESYS", "RADECSYS", "EQUINOX", "LONPOLE", "LATPOLE", "WCSAXES",
                "DATE-OBS", "MJD-OBS")


def _header_text(key: str, fetch: RangeFetch) -> tuple[str, int]:
    """The primary header's cards (up to END) and the byte offset where its data start."""
    raw = fetch(key, 0, HEADER_GUESS)
    end = _end_card(raw)
    while end < 0:
        more = fetch(key, len(raw), len(raw) + HEADER_GUESS)
        if not more:
            raise ValueError(f"no END card in {key}")
        raw += more
        end = _end_card(raw)
    return raw[:end + CARD].decode("ascii"), (end // BLOCK + 1) * BLOCK


def read_header(key: str, fetch: RangeFetch = net.get_range) -> tuple[fits.Header, int]:
    """The primary header of an object and the byte offset where its data start."""
    text, data_start = _header_text(key, fetch)
    return fits.Header.fromstring(text), data_start


def wcs_header(text: str) -> fits.Header:
    """Only the WCS_KEYWORDS cards of a header given as its 80-character cards."""
    cards = (text[i:i + CARD] for i in range(0, len(text), CARD))
    return fits.Header.fromstring("".join(c for c in cards if c.startswith(WCS_KEYWORDS))
                                  + "END".ljust(CARD))


def frame_wcs(header: fits.Header) -> WCS:
    """WCS (with SIP) of an L1b header. The deprecated RADECSYS keyword is renamed on a copy
    so astropy does not warn on every frame (warning filters are not thread-safe, and the
    readers run in threads)."""
    if "RADECSYS" in header and "RADESYS" not in header:
        header = header.copy()
        header.rename_keyword("RADECSYS", "RADESYS")
    return WCS(header)


def row_range(wcs: WCS, ny: int, grid: Grid) -> tuple[int, int] | None:
    """Rows [y0, y1) of the frame needed to cover the grid; None if the grid misses them."""
    ras, decs = grid_border(grid)
    _, y = wcs.all_world2pix(ras, decs, 0)
    if not np.all(np.isfinite(y)):
        return None
    y0 = max(int(np.floor(y.min())) - ROW_PAD, 0)
    y1 = min(int(np.ceil(y.max())) + ROW_PAD + 1, ny)
    return (y0, y1) if y1 > y0 else None


def read_exposure(frame: Frame, grid: Grid, fetch: RangeFetch = net.get_range) -> Exposure | None:
    """The rows of ``frame`` that cover ``grid``, or None when the frame misses the grid."""
    text, data_start = _header_text(frame.key, fetch)
    header = wcs_header(text)
    if header.get("BITPIX") != -32 or header.get("NAXIS") != 2:
        raise ValueError(f"{frame.key}: expected a 2-D float32 image")
    nx, ny = int(header["NAXIS1"]), int(header["NAXIS2"])
    wcs = frame_wcs(header)
    rows = row_range(wcs, ny, grid)
    if rows is None:
        return None
    y0, y1 = rows
    row_bytes = nx * 4
    raw = fetch(frame.key, data_start + y0 * row_bytes, data_start + y1 * row_bytes)
    if len(raw) != (y1 - y0) * row_bytes:
        raise ValueError(f"{frame.key}: short read ({len(raw)} bytes)")
    data = np.frombuffer(raw, dtype=">f4").reshape(y1 - y0, nx).astype(np.float32)
    return Exposure(frame=frame, data=data, wcs=wcs.slice((slice(y0, y1), slice(None))),
                    y0=y0, full_shape=(ny, nx), header=header)
