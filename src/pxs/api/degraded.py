"""Whether a built manifest is partial because an upstream fetch failed.

The manifest's top-level boolean `degraded` is authoritative when present. Until every
build writes it, the fixed warning sentences authored in `pxs.sources` and `pxs.catalogs`
are matched instead (they never contain upstream text).
"""

from __future__ import annotations

import re

_FAILED = re.compile(
    r"could not be fetched"
    r"|could not be loaded; the archive did not answer"
    r"|\d+ (?:WISE|SPHEREx) stacks?(?: or spectra)? failed"
)


def is_degraded(manifest: dict) -> bool:
    flag = manifest.get("degraded")
    if isinstance(flag, bool):
        return flag
    return any(isinstance(w, str) and _FAILED.search(w) for w in manifest.get("warnings", ()))
