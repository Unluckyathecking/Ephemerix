"""The curated body list (data/bodies.json) and strict parsing of a body designation.

User input never reaches Horizons as free text. `resolve` accepts either a designation
or name from the curated list, or one of two strict patterns:

- a numbered minor planet, 1 to 7 digits ("136108") -> Horizons "136108;"
- a comet designation ("C/2025 N1", "P/2019 LD2", "12P", "3I") -> "DES=...;CAP;NOFRAG"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BODIES_JSON = REPO / "data" / "bodies.json"

_NUMBERED = re.compile(r"[1-9][0-9]{0,6}")
_COMET = re.compile(r"(?:[CP]/(?:19|20)[0-9]{2} [A-HJ-Y][A-HJ-Z]?[0-9]{0,3}|[1-9][0-9]{0,3}[PI])")
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Body:
    """One Solar System body.

    designation: what the user types (e.g. "136108"). horizons: the exact Horizons
    COMMAND. kind: "dwarf planet", "TNO", "Centaur", "asteroid" or "comet".
    passes: survey passes that cover it, as "YYYY-MM-DD..YYYY-MM-DD" strings.
    """

    designation: str
    name: str
    horizons: str
    kind: str = ""
    blurb: str = ""
    composition: str = ""
    composition_ref: str = ""
    passes: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return _SLUG.sub("-", (self.name or self.designation).lower()).strip("-")


def load_bodies(path: Path = BODIES_JSON) -> tuple[Body, ...]:
    """Bodies listed under "bodies" in the curated JSON file."""
    raw = json.loads(path.read_text())
    out = []
    for b in raw["bodies"]:
        out.append(Body(designation=str(b["designation"]), name=str(b["name"]),
                        horizons=str(b["horizons"]), kind=str(b.get("type", "")),
                        blurb=str(b.get("blurb", "")),
                        composition=str(b.get("composition", "")),
                        composition_ref=str(b.get("composition_ref", "")),
                        passes=tuple(str(p) for p in b.get("passes", []))))
    return tuple(out)


def resolve(text: str, curated: tuple[Body, ...] | None = None) -> Body:
    """The Body for a user designation; ValueError unless curated or strictly valid."""
    s = " ".join(str(text).split())
    if not s or len(s) > 32:
        raise ValueError("designation must be 1-32 characters")
    for b in curated if curated is not None else load_bodies():
        if s.lower() in (b.designation.lower(), b.name.lower(), b.slug):
            return b
    if _NUMBERED.fullmatch(s):
        return Body(designation=s, name=s, horizons=f"{s};")
    if _COMET.fullmatch(s):
        return Body(designation=s, name=s, horizons=f"DES={s};CAP;NOFRAG", kind="comet")
    raise ValueError(f"not a known body or a valid designation: {s!r}")
