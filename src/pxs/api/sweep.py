"""Keep the upstream data caches (WISE, SPHEREx, catalogues) inside one size budget."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger("pxs.api.sweep")
_lock = threading.Lock()


def sweep(dirs: Iterable[Path], max_bytes: int) -> int:
    """Delete the oldest files across `dirs` until they total at most `max_bytes`.

    The caches are safe to delete at any time (they only save re-downloads). Returns the
    bytes removed. Files that vanish or cannot be removed are skipped.
    """
    with _lock:
        files: list[tuple[float, int, Path]] = []
        for root in dirs:
            for p in Path(root).rglob("*"):
                try:
                    if p.is_file():
                        st = p.stat()
                        files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    continue
        total = sum(size for _, size, _ in files)
        removed = 0
        for _, size, p in sorted(files):
            if total <= max_bytes:
                break
            try:
                p.unlink()
            except OSError:
                continue
            total -= size
            removed += size
        if removed:
            log.info("swept %d bytes from the upstream caches", removed)
        return removed
