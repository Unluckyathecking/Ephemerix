"""HTTP with retries, and a block cache for anonymous range reads from the public bucket.

The cache keeps fixed-size blocks under cache/spherex/blocks/<sha1 of key>/<block>_<index>,
so it is keyed by S3 key and byte range. Files are immutable for a given key, so blocks
never go stale; delete the directory at any time.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

import requests

from . import config

log = logging.getLogger(__name__)
T = TypeVar("T")

# fetch(key, start, end_exclusive) -> (bytes, total file size)
Fetcher = Callable[[str, int, int], tuple[bytes, int]]

# One session for the process: its connection pool is shared by every reading thread, so
# connections to the bucket are reused across frames, passes and builds (a per-thread
# session lost them whenever a short-lived pool thread ended). urllib3 pools are thread-safe.
_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4,
                                                         pool_maxsize=config.S3_MAX_CONCURRENT))
# At most this many range reads in flight to the bucket from this process.
_s3_slots = threading.BoundedSemaphore(config.S3_MAX_CONCURRENT)


class TransientError(Exception):
    """A failure worth retrying (timeout, connection reset, 5xx, 429)."""


def session() -> requests.Session:
    """The shared requests.Session, with the project User-Agent."""
    return _session


def with_retries(fn: Callable[[], T], what: str, retries: int = config.RETRIES) -> T:
    """Call fn, retrying TransientError and requests' network errors with backoff."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (TransientError, requests.ConnectionError, requests.Timeout) as e:
            if attempt == retries:
                raise
            delay = config.BACKOFF_S * 2**attempt * (1 + random.random() / 2)
            log.info("retry %d/%d for %s in %.1fs: %s", attempt + 1, retries, what, delay, e)
            time.sleep(delay)
    raise AssertionError("unreachable")


def check_status(r: requests.Response, what: str) -> None:
    """Raise TransientError for retryable statuses, HTTPError for other failures."""
    if r.status_code == 429 or r.status_code >= 500:
        raise TransientError(f"{what}: HTTP {r.status_code}")
    r.raise_for_status()


def http_fetch(key: str, start: int, end: int) -> tuple[bytes, int]:
    """Ranged GET of bytes [start, end) of `key` in the public bucket."""
    what = f"{key}[{start}:{end}]"

    def go() -> tuple[bytes, int]:
        with _s3_slots:
            r = session().get(config.BUCKET_URL + key,
                              headers={"Range": f"bytes={start}-{end - 1}"},
                              timeout=config.TIMEOUT_S)
        check_status(r, what)
        if r.status_code != 206:
            raise TransientError(f"{what}: expected HTTP 206, got {r.status_code}")
        total = int(r.headers["Content-Range"].rsplit("/", 1)[1])
        if len(r.content) != min(end, total) - start:
            raise TransientError(f"{what}: short read of {len(r.content)} B")
        return r.content, total

    return with_retries(go, what)


def _runs(indices: Iterable[int]) -> list[tuple[int, int]]:
    """Group sorted block indices into contiguous (first, last) runs."""
    out: list[tuple[int, int]] = []
    for i in sorted(set(indices)):
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


class BlockStore:
    """Byte ranges of bucket objects, served from the disk cache or fetched in blocks.

    `fetch` is injectable so tests can replay recorded bytes with no network.
    Counters `gets` and `bytes_fetched` cover network traffic only.
    """

    def __init__(self, fetch: Fetcher = http_fetch, root: Path | None = None,
                 block: int = config.BLOCK_BYTES) -> None:
        self._fetch = fetch
        self.root = (root or config.cache_dir()) / "blocks"
        self.block = block
        self._lock = threading.Lock()
        self.gets = 0
        self.bytes_fetched = 0

    def _dir(self, key: str) -> Path:
        return self.root / hashlib.sha1(key.encode()).hexdigest()

    def _path(self, key: str, i: int) -> Path:
        return self._dir(key) / f"{self.block}_{i}"

    def size(self, key: str) -> int:
        """Total size of the object in bytes (fetches block 0 the first time)."""
        p = self._dir(key) / "size"
        if not p.exists():
            self._get_run(key, 0, 0)
        return int(p.read_text())

    def _get_run(self, key: str, first: int, last: int) -> None:
        start = first * self.block
        known = self._dir(key) / "size"
        end = (last + 1) * self.block
        if known.exists():
            end = min(end, int(known.read_text()))
        data, total = self._fetch(key, start, end)
        with self._lock:
            self.gets += 1
            self.bytes_fetched += len(data)
        d = self._dir(key)
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / "size", str(total).encode())
        if not (d / "key").exists():
            _atomic_write(d / "key", key.encode())
        for i in range(first, last + 1):
            chunk = data[(i - first) * self.block:(i - first + 1) * self.block]
            if chunk:
                _atomic_write(self._path(key, i), chunk)

    def _missing(self, key: str, start: int, end: int) -> list[int]:
        first, last = start // self.block, (end - 1) // self.block
        return [i for i in range(first, last + 1) if not self._path(key, i).exists()]

    def prefetch(self, key: str, ranges: Iterable[tuple[int, int]],
                 workers: int = config.BATCH_WORKERS) -> None:
        """Fetch every missing block of the given [start, end) ranges in one parallel batch."""
        missing = [i for a, b in ranges if b > a for i in self._missing(key, a, b)]
        runs = _runs(missing)
        if len(runs) <= 1:
            for a, b in runs:
                self._get_run(key, a, b)
            return
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda r: self._get_run(key, *r), runs))

    def read(self, key: str, start: int, end: int) -> bytes:
        """Bytes [start, end) of `key`; missing blocks are fetched in contiguous runs."""
        if end <= start:
            return b""
        for a, b in _runs(self._missing(key, start, end)):
            self._get_run(key, a, b)
        first, last = start // self.block, (end - 1) // self.block
        data = b"".join(self._path(key, i).read_bytes() for i in range(first, last + 1))
        off = start - first * self.block
        return data[off:off + end - start]


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
