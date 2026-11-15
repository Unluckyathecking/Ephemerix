"""On-disk cache of final per-frame stamps, so a warm rebuild needs no network and no byte cache.

One compressed .npz per (S3 key, position, stamp size, with or without PSF) under
cache/spherex/stamps/. A frame that does not contain the position is cached too, as an
"off" entry, so it is not looked up again. Failures are never cached. Files on the
bucket are immutable for a given key, so entries never go stale; delete the directory
at any time. Bump VERSION if the Stamp contents change.

The most recent MEMORY_ENTRIES entries are also kept in memory, so a stamp read once in a
build (e.g. by the pass prefetch) is not decompressed from disk again by every window.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from . import config
from .read import Stamp

log = logging.getLogger(__name__)

VERSION = 1
_OFF = "off"
_ARRAYS = ("image", "flags", "variance", "zodi")
_SCALARS = ("x0", "y0", "xpix", "ypix", "wave_um", "band_um", "mjd", "detector")
MISS = object()  # returned by `get` when nothing is cached
MEMORY_ENTRIES = 1024  # per process; up to ~70 MB of 240" stack stamps (each worker has its own)

_memory: OrderedDict[str, Stamp | None] = OrderedDict()
_memory_lock = threading.Lock()


def _remember(tag: str, stamp: Stamp | None) -> None:
    with _memory_lock:
        _memory[tag] = stamp
        _memory.move_to_end(tag)
        while len(_memory) > MEMORY_ENTRIES:
            _memory.popitem(last=False)


def clear_memory() -> None:
    """Forget the in-memory entries (the disk cache is untouched)."""
    with _memory_lock:
        _memory.clear()


def _tag(key: str, ra: float, dec: float, half: int, with_psf: bool) -> str:
    return f"v{VERSION}|{key}|{ra:.7f}|{dec:.7f}|{half}|{int(with_psf)}"


def _path(key: str, ra: float, dec: float, half: int, with_psf: bool) -> Path:
    h = hashlib.sha1(_tag(key, ra, dec, half, with_psf).encode()).hexdigest()
    return config.cache_dir() / "stamps" / h[:2] / f"{h}.npz"


def _to_arrays(s: Stamp) -> dict[str, np.ndarray]:
    out = {k: getattr(s, k) for k in _ARRAYS}
    out.update({k: np.asarray(getattr(s, k)) for k in _SCALARS})
    out["key"], out["header"] = np.asarray(s.key), np.asarray(s.header)
    if s.psf is not None:
        out["psf"] = s.psf
    if s.wave_table is not None:
        out.update(wave_x=s.wave_table[0], wave_y=s.wave_table[1], wave_v=s.wave_table[2])
    return out


def _from_arrays(z: np.lib.npyio.NpzFile) -> Stamp:
    arrays = {k: z[k] for k in _ARRAYS}
    psf = z["psf"] if "psf" in z.files else None
    for a in [*arrays.values(), *([psf] if psf is not None else [])]:
        a.setflags(write=False)
    table = (z["wave_x"], z["wave_y"], z["wave_v"]) if "wave_x" in z.files else None
    scalars = {k: z[k].item() for k in _SCALARS}
    return Stamp(key=str(z["key"]), header=str(z["header"]), psf=psf, wave_table=table,
                 **arrays, **scalars)


def get(key: str, ra: float, dec: float, half: int, with_psf: bool) -> Stamp | None | object:
    """The cached Stamp, None for a cached "off detector", or MISS."""
    tag = f"{config.cache_dir()}|{_tag(key, ra, dec, half, with_psf)}"
    with _memory_lock:
        if tag in _memory:
            return _memory[tag]
    p = _path(key, ra, dec, half, with_psf)
    if not p.exists():
        return MISS
    try:
        with np.load(p, allow_pickle=False) as z:
            stamp = None if _OFF in z.files else _from_arrays(z)
    except (OSError, ValueError, KeyError) as exc:
        log.warning("ignoring unreadable stamp cache entry %s: %s", p.name, exc)
        return MISS
    _remember(tag, stamp)
    return stamp


def put(key: str, ra: float, dec: float, half: int, with_psf: bool, stamp: Stamp | None) -> None:
    """Store a stamp, or None for "the position is off this frame". Atomic per file."""
    _remember(f"{config.cache_dir()}|{_tag(key, ra, dec, half, with_psf)}", stamp)
    p = _path(key, ra, dec, half, with_psf)
    p.parent.mkdir(parents=True, exist_ok=True)
    arrays = {_OFF: np.asarray(1)} if stamp is None else _to_arrays(stamp)
    tmp = p.with_name(f".{p.stem}.{os.getpid()}.{threading.get_ident()}.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(p)
