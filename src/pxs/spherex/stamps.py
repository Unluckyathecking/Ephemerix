"""Read many stamps concurrently. A frame that fails after retries is skipped and counted."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pxs.astrometry import decimal_year, propagate

from . import config, stampcache
from .net import BlockStore
from .read import Stamp, read_stamp
from .types import Frame, Target

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Batch:
    """Stamps that were read, plus counts of frames that failed or missed the position."""

    stamps: tuple[tuple[Frame, Stamp], ...]
    n_failed: int
    n_off_detector: int

    def warnings(self) -> tuple[str, ...]:
        if not self.n_failed:
            return ()
        return (f"{self.n_failed} frame(s) could not be read and were skipped",)


def position_at(target: Target, mjd: float) -> tuple[float, float]:
    """Target (ra, dec) in degrees at an MJD, by linear proper motion (no parallax)."""
    if not target.has_pm:
        return target.ra, target.dec
    ra, dec = propagate(target.ra, target.dec, target.epoch, target.pmra_masyr,
                        target.pmdec_masyr, float(decimal_year(mjd)))
    return float(ra), float(dec)


def _read_uncached(frame: Frame, ra: float, dec: float, half: int, with_psf: bool,
                   store: BlockStore | None) -> Stamp | None:
    """read_stamp through `store`, or, without one, the shared byte cache if it is enabled,
    else a throwaway block store that lives only while this frame is read."""
    if store is not None or config.byte_cache_enabled():
        return read_stamp(store or BlockStore(), frame.s3_key, ra, dec, half, with_psf)
    with tempfile.TemporaryDirectory(prefix="pxs-blocks-") as tmp:
        return read_stamp(BlockStore(root=Path(tmp)), frame.s3_key, ra, dec, half, with_psf)


def read_one(frame: Frame, ra: float, dec: float, half: int = config.STAMP_HALF,
             with_psf: bool = True, store: BlockStore | None = None) -> Stamp | None:
    """One stamp, from the stamp cache when present (else read and cached). None: off frame."""
    hit = stampcache.get(frame.s3_key, ra, dec, half, with_psf)
    if hit is not stampcache.MISS:
        return hit  # type: ignore[return-value]
    stamp = _read_uncached(frame, ra, dec, half, with_psf, store)
    stampcache.put(frame.s3_key, ra, dec, half, with_psf, stamp)
    return stamp


def read_many(jobs: Sequence[tuple[Frame, float, float]], half: int = config.STAMP_HALF,
              with_psf: bool = True, store: BlockStore | None = None,
              workers: int = config.MAX_WORKERS) -> Batch:
    """Read a stamp at (ra, dec) for each (frame, ra, dec), at most `workers` at a time.

    Stamps come from the stamp cache when present; `store` (default: the byte cache when
    PXS_BYTE_CACHE=1, else none kept) is only used for frames not cached yet.
    """

    def one(job: tuple[Frame, float, float]) -> tuple[Frame, Stamp | None, bool]:
        frame, ra, dec = job
        try:
            return frame, read_one(frame, ra, dec, half, with_psf, store), False
        except Exception as e:  # noqa: BLE001 - one bad frame must never stop the pass
            log.warning("skipping %s D%d: %s", frame.obs_id, frame.detector, e)
            return frame, None, True

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, jobs))
    ok = tuple((f, s) for f, s, _ in results if s is not None)
    failed = sum(1 for _, _, bad in results if bad)
    off = sum(1 for _, s, bad in results if s is None and not bad)
    if off:
        log.info("%d frame(s) do not contain the position", off)
    return Batch(ok, failed, off)
