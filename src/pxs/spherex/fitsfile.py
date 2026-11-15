"""A seekable read-only file over one bucket object, backed by a BlockStore.

astropy.io.fits opens it like a local file (public API, lazy HDUs, no memmap) and every
read it makes becomes a cached range read.
"""

from __future__ import annotations

import io

from .net import BlockStore


class RangeFile(io.RawIOBase):
    """File-like view of `key` in the bucket. Reads are served by `store`."""

    def __init__(self, store: BlockStore, key: str) -> None:
        super().__init__()
        self._store = store
        self._key = key
        self._size = store.size(key)
        self._pos = 0
        self.name = key.rsplit("/", 1)[-1]
        self.mode = "rb"

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buf: bytearray | memoryview) -> int:  # type: ignore[override]
        n = min(len(buf), self._size - self._pos)
        if n <= 0:
            return 0
        buf[:n] = self._store.read(self._key, self._pos, self._pos + n)
        self._pos += n
        return n
