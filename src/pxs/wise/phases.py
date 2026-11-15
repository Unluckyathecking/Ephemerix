"""WISE mission phases and where their single-exposure frames live.

Every phase keeps its W1/W2 L1b "int" frames in s3://nasa-irsa-wise with the same layout:
``{prefix}{scangrp}/{scan_id}/{frame:03d}/{scan_id}{frame:03d}-w{1,2}-int-1b.fits``, where
``scangrp`` is the last two characters of the scan id. The int image is plain FITS (float32,
DN), so it can be range-read; the masks next to it are gzipped.
"""

from __future__ import annotations

from dataclasses import dataclass

BANDS = ("W1", "W2")


@dataclass(frozen=True)
class Phase:
    """One mission phase: its IRSA SIA2 collection, TAP frame table, bucket and IBE prefixes."""

    name: str
    sia_collection: str
    tap_table: str
    bucket_prefix: str
    ibe_prefix: str


PHASES: tuple[Phase, ...] = (
    Phase("allsky", "wise_allsky", "allsky_4band_p1bm_frm",
          "wise/allsky/images/4band_p1bm_frm/",
          "https://irsa.ipac.caltech.edu/ibe/data/wise/allsky/4band_p1bm_frm/"),
    Phase("3band", "wise_3bandcryo", "allsky_3band_p1bm_frm",
          "wise/cryo-3band/images/3band_p1bm_frm/",
          "https://irsa.ipac.caltech.edu/ibe/data/wise/cryo_3band/3band_p1bm_frm/"),
    Phase("postcryo", "wise_2bandcryo", "allsky_2band_p1bm_frm",
          "wise/postcryo/images/2band_p1bm_frm/",
          "https://irsa.ipac.caltech.edu/ibe/data/wise/postcryo/2band_p1bm_frm/"),
    Phase("neowiser", "neowiser", "neowiser_p1bm_frm",
          "wise/neowiser/images/p1bm_frm/",
          "https://irsa.ipac.caltech.edu/ibe/data/wise/neowiser/p1bm_frm/"),
)
_BY_NAME = {p.name: p for p in PHASES}


def phase(name: str) -> Phase:
    """The phase called ``name`` ("allsky", "3band", "postcryo" or "neowiser")."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown WISE phase {name!r}") from None


def phase_of_url(url: str) -> Phase:
    """The phase an IRSA IBE ``access_url`` belongs to."""
    for p in PHASES:
        if url.startswith(p.ibe_prefix):
            return p
    raise ValueError(f"unknown WISE access_url prefix: {url}")


def bucket_key(phase_name: str, scan_id: str, frame_num: int, band: str) -> str:
    """Object key of a W1/W2 int frame in s3://nasa-irsa-wise."""
    if band not in BANDS:
        raise ValueError(f"band must be one of {BANDS}, got {band!r}")
    if len(scan_id) != 6 or not 0 <= frame_num <= 999:
        raise ValueError(f"bad scan/frame id {scan_id!r}/{frame_num}")
    stem = f"{scan_id}{frame_num:03d}"
    return (f"{phase(phase_name).bucket_prefix}{scan_id[-2:]}/{scan_id}/{frame_num:03d}/"
            f"{stem}-w{band[1]}-int-1b.fits")
