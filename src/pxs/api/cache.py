"""On-disk cache of finished views, keyed by hex digest, with a size cap and LRU eviction.

Layout under the cache directory:
    views/<key>/manifest.json, thumb.png, frames/*.png   finished, immutable
    tmp/<key>-<job>/                                    a build in progress
A view counts as cached only once its directory is in `views/` (moved there atomically).
A view built from partial data ("degraded") carries a `degraded` marker file holding its
expiry time; it is served without long caching, dropped once expired so a retry rebuilds,
evicted before any good view, and never causes a good view to be evicted.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pxs.api.params import KEY_RE

log = logging.getLogger("pxs.api.cache")

DEGRADED_MARKER = "degraded"
FILE_RE = re.compile(r"manifest\.json|thumb\.png|(?:frames|body)/[A-Za-z0-9._-]{1,120}\.png")


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


class ViewCache:
    """Thread-safe store of finished view directories."""

    def __init__(self, root: Path, max_bytes: int, degraded_ttl_s: float = 600.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root).resolve()
        self.degraded_ttl_s, self._clock = degraded_ttl_s, clock
        self._degraded: dict[str, float] = {}  # key -> expiry (survives restarts via marker)
        self.views = self.root / "views"
        self.tmp = self.root / "tmp"
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.views.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)  # half-built views from a previous run
        self.tmp.mkdir(parents=True, exist_ok=True)
        self._sizes = {p.name: _dir_size(p) for p in self.views.iterdir()
                       if p.is_dir() and KEY_RE.fullmatch(p.name)}
        for k in self._sizes:
            marker = self.views / k / DEGRADED_MARKER
            if marker.is_file():
                try:
                    self._degraded[k] = float(marker.read_text())
                except (OSError, ValueError):
                    self._degraded[k] = 0.0  # unreadable marker: treat as expired
        for k in list(self._degraded):
            self._expire(k)

    def _expire(self, key: str) -> None:
        """Drop a degraded view whose time is up (the caller may hold the lock or not)."""
        with self._lock:
            if key in self._degraded and self._degraded[key] <= self._clock():
                del self._degraded[key]
                self._sizes.pop(key, None)
                shutil.rmtree(self.views / key, ignore_errors=True)
                log.info("expired degraded view %s", key)

    def is_degraded(self, key: str) -> bool:
        self._expire(key)
        return key in self._degraded

    def has(self, key: str) -> bool:
        if KEY_RE.fullmatch(key) is None:
            return False
        self._expire(key)
        return (self.views / key / "manifest.json").is_file()

    def touch(self, key: str) -> None:
        """Mark a view as recently used (its directory mtime is the LRU clock)."""
        try:
            os.utime(self.views / key)
        except OSError:
            log.warning("could not touch cached view %s", key)

    def file(self, key: str, rel: str) -> Path | None:
        """Absolute path of one served file, or None if the request is not a cache file."""
        if KEY_RE.fullmatch(key) is None or FILE_RE.fullmatch(rel) is None:
            return None
        self._expire(key)
        path = (self.views / key / rel).resolve()
        if not path.is_relative_to(self.views) or not path.is_file():
            return None
        return path

    def work_dir(self, key: str, job_id: str) -> Path:
        path = self.tmp / f"{key}-{job_id}"
        path.mkdir(parents=True)
        return path

    def discard(self, work: Path) -> None:
        shutil.rmtree(work, ignore_errors=True)

    def commit(self, key: str, work: Path, degraded: bool = False) -> None:
        """Move a finished build into place, then evict old views beyond the size cap.

        A degraded build gets an expiry marker and never replaces an existing view. A good
        build replaces an existing degraded one.
        """
        dest = self.views / key
        if degraded:
            (work / DEGRADED_MARKER).write_text(repr(self._clock() + self.degraded_ttl_s))
        size = _dir_size(work)
        with self._lock:
            if dest.exists() and not (key in self._degraded and not degraded):
                shutil.rmtree(work, ignore_errors=True)
            else:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                    self._degraded.pop(key, None)
                os.replace(work, dest)
                self._sizes[key] = size
                if degraded:
                    self._degraded[key] = self._clock() + self.degraded_ttl_s
            self._evict(keep=key)

    def _evict(self, keep: str) -> None:
        """Evict degraded views first, then good ones oldest first, until under the cap.

        A degraded view is short-lived, so it is allowed to overshoot the cap rather than
        push out a good view.
        """
        total = sum(self._sizes.values())
        if total <= self.max_bytes:
            return

        def mtime(k: str) -> float:
            try:
                return (self.views / k).stat().st_mtime
            except OSError:
                return 0.0
        order = sorted((k for k in self._sizes if k != keep and k in self._degraded), key=mtime)
        if keep not in self._degraded:
            order += sorted((k for k in self._sizes if k != keep and k not in self._degraded),
                            key=mtime)
        for k in order:
            if total <= self.max_bytes:
                break
            total -= self._sizes.pop(k)
            self._degraded.pop(k, None)
            shutil.rmtree(self.views / k, ignore_errors=True)
            log.info("evicted cached view %s", k)

    def stats(self) -> dict:
        with self._lock:
            return {"views": len(self._sizes), "bytes": sum(self._sizes.values()),
                    "max_bytes": self.max_bytes}
