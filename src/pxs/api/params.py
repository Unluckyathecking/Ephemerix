"""Query validation, normalisation and the cache key for one view request."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from pxs.api.config import PIPELINE_VERSION
from pxs.sources import Target

FOV_STEPS: tuple[float, ...] = (120.0, 240.0, 360.0, 480.0)
DEFAULT_FOV = 240.0
DEFAULT_EPOCH = 2016.0  # Gaia DR3 reference epoch
EPOCH_RANGE = (1990.0, 2035.0)
PM_LIMIT = 20000.0
NAME_MAX = 80
NAME_RE = re.compile(r"[A-Za-z0-9 +\-_.()\[\]':*/]+")
VIEW_KEYS = frozenset({"ra", "dec", "pmra", "pmdec", "epoch", "fov", "name"})
KEY_RE = re.compile(r"[0-9a-f]{64}")


class ParamError(ValueError):
    """A request parameter is invalid; the message is safe to show to a user."""


@dataclass(frozen=True)
class ViewParams:
    """A normalised view request. `name` is cosmetic and not part of the cache key."""

    ra: float
    dec: float
    pmra: float | None
    pmdec: float | None
    epoch: float
    fov: float
    name: str | None = None

    @property
    def key(self) -> str:
        """Hex digest of the normalised parameters that change the built view."""
        has_pm = self.pmra is not None
        body = {"ra": self.ra, "dec": self.dec, "pmra": self.pmra, "pmdec": self.pmdec,
                "epoch": self.epoch if has_pm else None, "fov": self.fov, "v": PIPELINE_VERSION}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def target(self) -> Target:
        return Target(name=None, ra=self.ra, dec=self.dec, epoch=self.epoch,
                      pmra_masyr=self.pmra, pmdec_masyr=self.pmdec, fov_arcsec=self.fov)


def single_values(items: Iterable[tuple[str, str]], allowed: frozenset[str]) -> dict[str, str]:
    """Query pairs as a dict. Rejects unknown and repeated keys."""
    out: dict[str, str] = {}
    for k, v in items:
        if k not in allowed:
            raise ParamError(f"Unknown parameter '{k[:40]}'. Allowed: {', '.join(sorted(allowed))}.")
        if k in out:
            raise ParamError(f"Parameter '{k}' was given more than once.")
        out[k] = v
    return out


def _number(q: dict[str, str], key: str) -> float | None:
    raw = q.get(key)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ParamError(f"'{key}' must be a number.") from None
    if not math.isfinite(value):
        raise ParamError(f"'{key}' must be a finite number.")
    return value


def _in_range(key: str, value: float, low: float, high: float, what: str) -> None:
    if not low <= value <= high:
        raise ParamError(f"'{key}' must be {what}; got {value:g}.")


def snap_fov(value: float) -> float:
    """Nearest allowed field of view; values outside the allowed span are rejected."""
    _in_range("fov", value, FOV_STEPS[0], FOV_STEPS[-1],
              f"between {FOV_STEPS[0]:g} and {FOV_STEPS[-1]:g} arcsec")
    return min(FOV_STEPS, key=lambda s: abs(s - value))


def clean_name(raw: str | None) -> str | None:
    """A display name, or None. Only plain catalogue-name characters are accepted."""
    if raw is None or raw.strip() == "":
        return None
    name = raw.strip()
    if len(name) > NAME_MAX:
        raise ParamError(f"'name' must be at most {NAME_MAX} characters.")
    if not NAME_RE.fullmatch(name):
        raise ParamError("'name' may contain only letters, digits, spaces and + - _ . ( ) [ ] ' : * /")
    return name


def _proper_motion(q: dict[str, str]) -> tuple[float | None, float | None]:
    pmra, pmdec = _number(q, "pmra"), _number(q, "pmdec")
    if (pmra is None) != (pmdec is None):
        raise ParamError("Give both 'pmra' and 'pmdec', or neither.")
    for key, v in (("pmra", pmra), ("pmdec", pmdec)):
        if v is not None and abs(v) >= PM_LIMIT:
            raise ParamError(f"'{key}' must be under {PM_LIMIT:g} mas/yr in size; got {v:g}.")
    if pmra is None:
        return None, None
    return round(pmra, 1) + 0.0, round(pmdec, 1) + 0.0


def parse_view(items: Iterable[tuple[str, str]]) -> ViewParams:
    """Validate and normalise a /api/view query. Raises ParamError with a readable message."""
    q = single_values(items, VIEW_KEYS)
    ra, dec = _number(q, "ra"), _number(q, "dec")
    if ra is None or dec is None:
        raise ParamError("'ra' and 'dec' are required, in decimal degrees.")
    _in_range("ra", ra, 0.0, 360.0, "between 0 and 360 degrees")
    _in_range("dec", dec, -90.0, 90.0, "between -90 and 90 degrees")
    pmra, pmdec = _proper_motion(q)
    epoch = _number(q, "epoch")
    if epoch is not None:
        _in_range("epoch", epoch, *EPOCH_RANGE, f"a year from {EPOCH_RANGE[0]:g} to {EPOCH_RANGE[1]:g}")
    fov = _number(q, "fov")
    return ViewParams(
        ra=round(ra, 5) % 360.0 + 0.0,
        dec=round(dec, 5) + 0.0,
        pmra=pmra,
        pmdec=pmdec,
        epoch=round(epoch if epoch is not None else DEFAULT_EPOCH, 3),
        fov=snap_fov(fov) if fov is not None else DEFAULT_FOV,
        name=clean_name(q.get("name")),
    )
