"""The one `Target` type, and loading gallery targets from `data/targets.json`.

Units: degrees (ICRS) at `epoch` (decimal year), proper motion in mas/yr with pmra
already multiplied by cos dec, field of view in arcsec.

`data/targets.json` is a JSON list of objects. The keys read are the `Target` fields
below (parallax in mas; `group` is the gallery heading the target is listed under); every
other key (for example `notes`, `sources`) is accepted and ignored, so the file can carry
more than the pipeline uses.
"""

from __future__ import annotations

import json
import logging
import math
import numbers
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class TargetError(ValueError):
    """A target, or a targets.json entry, is malformed."""


def check_position(ra: float, dec: float) -> None:
    """Raise unless ra is a finite number in [0, 360) deg and dec one in [-90, 90] deg."""
    if not (isinstance(ra, numbers.Real) and isinstance(dec, numbers.Real)):
        raise TypeError(f"ra and dec must be numbers, got {ra!r}, {dec!r}")
    if not (math.isfinite(ra) and math.isfinite(dec)):
        raise ValueError(f"ra and dec must be finite, got {ra}, {dec}")
    if not 0.0 <= ra < 360.0:
        raise ValueError(f"ra must be in [0, 360) deg, got {ra}")
    if not -90.0 <= dec <= 90.0:
        raise ValueError(f"dec must be in [-90, 90] deg, got {dec}")


def _check_finite(name: str, value: float | None, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


@dataclass(frozen=True)
class Target:
    """A sky position with optional proper motion, plus optional gallery fields.

    Both proper-motion components are None when unknown. Validated at construction.
    """

    name: str | None
    ra: float
    dec: float
    epoch: float
    pmra_masyr: float | None = None
    pmdec_masyr: float | None = None
    slug: str | None = None
    blurb: str | None = None
    known_type: str | None = None
    known_type_ref: str | None = None
    fov_arcsec: float | None = None
    w1_mag: float | None = None
    w2_mag: float | None = None
    parallax_mas: float | None = None
    group: str | None = None

    def __post_init__(self) -> None:
        check_position(self.ra, self.dec)
        _check_finite("epoch", self.epoch)
        _check_finite("pmra_masyr", self.pmra_masyr, optional=True)
        _check_finite("pmdec_masyr", self.pmdec_masyr, optional=True)
        if (self.pmra_masyr is None) != (self.pmdec_masyr is None):
            raise ValueError("give both proper-motion components or neither")
        _check_finite("fov_arcsec", self.fov_arcsec, optional=True)
        _check_finite("w1_mag", self.w1_mag, optional=True)
        _check_finite("w2_mag", self.w2_mag, optional=True)
        _check_finite("parallax_mas", self.parallax_mas, optional=True)
        if self.fov_arcsec is not None and self.fov_arcsec <= 0:
            raise ValueError(f"fov_arcsec must be > 0, got {self.fov_arcsec}")

    @property
    def has_pm(self) -> bool:
        return self.pmra_masyr is not None and self.pmdec_masyr is not None


# --- targets.json -----------------------------------------------------------------------

_REQUIRED = ("name", "ra", "dec", "epoch")
_NUMERIC = ("ra", "dec", "epoch", "pmra_masyr", "pmdec_masyr", "fov_arcsec", "w1_mag",
            "w2_mag", "parallax_mas")
_STRINGS = tuple(f.name for f in fields(Target) if f.name not in _NUMERIC)


def slugify(name: str) -> str:
    """URL-safe slug of a name: lower case, runs of other characters become one dash."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _number(entry: dict, key: str, where: str) -> float | None:
    v = entry.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise TargetError(f"{where}: '{key}' must be a number, got {v!r}")
    return float(v)


def target_from_dict(entry: Any, where: str = "target") -> Target:
    """Validate one dict and build a Target. Keys that are not Target fields are ignored."""
    if not isinstance(entry, dict):
        raise TargetError(f"{where}: expected an object, got {type(entry).__name__}")
    missing = [k for k in _REQUIRED if entry.get(k) is None]
    if missing:
        raise TargetError(f"{where}: missing {missing}; keys found: {sorted(entry)}")
    values = {k: _number(entry, k, where) for k in _NUMERIC}
    strings = {k: entry.get(k) for k in _STRINGS}
    for k, v in strings.items():
        if v is not None and not isinstance(v, str):
            raise TargetError(f"{where}: '{k}' must be a string, got {v!r}")
    slug = strings.pop("slug") or slugify(strings["name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise TargetError(f"{where}: slug {slug!r} is not URL-safe")
    try:
        return Target(**strings, **values, slug=slug)
    except (TypeError, ValueError) as exc:
        raise TargetError(f"{where}: {exc}") from exc


def load_targets(path: Path) -> list[Target]:
    """Read and validate a JSON list of targets. Raises TargetError naming the bad entry."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise TargetError(f"{path}: expected a JSON list of targets")
    targets = [
        target_from_dict(e, f"{path} entry {i} ({e.get('name') if isinstance(e, dict) else e!r})")
        for i, e in enumerate(raw)
    ]
    slugs = [t.slug for t in targets]
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    if dupes:
        raise TargetError(f"{path}: duplicate slugs {dupes}")
    return targets
