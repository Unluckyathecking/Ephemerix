"""Export the runtime dependencies exactly as uv.lock pins them, for the Modal image.

`modal_app.py` calls `export_requirements` when you deploy, so the image installs the same
versions CI tested and the Dockerfile ships (`uv sync --frozen --no-dev`). Run from a clean
checkout with `uv` on the PATH; no other step is needed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# name[extras]==version, optionally followed by an environment marker
_PINNED = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]+\])?==[^\s;=<>!~]+(?:\s*;.+)?")

EXPORT_ARGS = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes",
               "--format", "requirements-txt"]


def pinned_lines(text: str) -> list[str]:
    """The requirement lines of an exported file; raises ValueError on any unpinned one."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _PINNED.fullmatch(line):
            raise ValueError(f"not an exact pin: {line!r}")
        lines.append(line)
    if not lines:
        raise ValueError("no requirements exported")
    return lines


def export_requirements(repo: Path, out: Path) -> Path:
    """Write the pinned runtime requirements from `repo`/uv.lock to `out` and return it."""
    done = subprocess.run(EXPORT_ARGS, cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"uv export failed: {done.stderr.strip()}")
    lines = pinned_lines(done.stdout)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out
