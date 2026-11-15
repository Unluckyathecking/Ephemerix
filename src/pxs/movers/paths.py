"""Where the moving-object search keeps its cache (override with PXS_CACHE)."""

from __future__ import annotations

import os
from pathlib import Path


def cache_root() -> Path:
    """cache/movers under PXS_CACHE (default ./cache). Safe to delete at any time."""
    env = os.environ.get("PXS_CACHE")
    return (Path(env) if env else Path.cwd() / "cache") / "movers"
