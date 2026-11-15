"""Solar System body names: validation, resolution through JPL SBDB, and the build key.

User text never reaches JPL Horizons. A name is checked against a strict charset, looked up
in the curated list (data/bodies.json) and otherwise in the JPL Small-Body Database API
(one fixed host and path, the name only URL-quoted). The Horizons COMMAND is then built
from SBDB's own designation fields, each re-checked against a strict pattern, so an odd
SBDB answer can only make a lookup fail. Answers (including misses) are cached in memory;
an SBDB outage is not cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import quote

import requests

from pxs.api.config import PIPELINE_VERSION
from pxs.api.params import ParamError
from pxs.api.resolve import Fetch, http_fetch
from pxs.solarsystem.bodies import Body, load_bodies

log = logging.getLogger("pxs.api.bodies")

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
BODY_MAX = 40
BODY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 /'()._-]*")
CACHE_SIZE = 512
MAX_SUGGESTIONS = 5

NOT_FOUND = "No Solar System body by that name was found in the JPL Small-Body Database."
AMBIGUOUS = "More than one Solar System body matches that name. Did you mean one of these?"
SBDB_DOWN = ("The JPL Small-Body Database did not answer, so the name could not be looked "
             "up. Try again shortly.")

_NUMBERED = re.compile(r"[1-9][0-9]{0,6}")
_PROVISIONAL = re.compile(r"(?:18|19|20)[0-9]{2} [A-Z]{2}[0-9]{0,4}")
_COMET = re.compile(r"[1-9][0-9]{0,3}[PI]|[CPDXI]/(?:18|19|20)[0-9]{2} [A-HJ-Y][A-HJ-Z]?[0-9]{0,3}")
_LABEL = re.compile(r"[A-Za-z0-9 /'()._*-]{1,80}")


def clean_body_name(raw: str | None) -> str:
    """The name with spaces collapsed. ParamError (a readable sentence) when unusable."""
    name = " ".join(str(raw or "").split())
    if not name:
        raise ParamError("'name' is required: the name or designation of a Solar System body.")
    if len(name) > BODY_MAX:
        raise ParamError(f"'name' must be at most {BODY_MAX} characters.")
    if not BODY_RE.fullmatch(name):
        raise ParamError("'name' may contain only letters, digits, spaces and / ' ( ) . _ -")
    return name


def horizons_command(obj: dict) -> str | None:
    """The Horizons COMMAND for an SBDB `object`, or None when its designation is unusual."""
    kind, des, prefix = str(obj.get("kind", "")), str(obj.get("des", "")), obj.get("prefix")
    if kind == "an" and _NUMBERED.fullmatch(des):
        return f"{des};"
    if kind == "au" and _PROVISIONAL.fullmatch(des):
        return f"DES={des};"
    if kind in ("cn", "cu"):
        full = des if _COMET.fullmatch(des) else f"{prefix}/{des}"
        if _COMET.fullmatch(full):
            return f"DES={full};CAP;NOFRAG"
    return None


def _designation(obj: dict, command: str) -> str:
    """What the site puts in its URL: SBDB's designation, prefixed for a comet."""
    des = str(obj["des"])
    return command[4:].split(";")[0] if command.startswith("DES=") and "/" in command else des


def _label(text: object, fallback: str) -> str:
    s = " ".join(str(text or "").split())
    return s if _LABEL.fullmatch(s) else fallback


def _suggestions(items: object) -> list[dict]:
    """SBDB's candidates as {designation, name}. The designation (SBDB `pdes`) is what to
    look up next: SBDB refuses its own display names (they contain parentheses)."""
    out = []
    for x in items if isinstance(items, list) else []:
        des = " ".join(str(x.get("pdes", "")).split()) if isinstance(x, dict) else ""
        if des and len(des) <= BODY_MAX and BODY_RE.fullmatch(des):
            out.append({"designation": des, "name": _label(x.get("name"), des)})
    return out[:MAX_SUGGESTIONS]


def _from_sbdb(data: dict) -> dict:
    """A resolver answer from one decoded SBDB response."""
    if str(data.get("code")) == "300":
        return {"resolved": False, "message": AMBIGUOUS,
                "did_you_mean": _suggestions(data.get("list"))}
    obj = data.get("object")
    command = horizons_command(obj) if isinstance(obj, dict) else None
    if command is None:
        return {"resolved": False, "message": NOT_FOUND, "did_you_mean": []}
    des = _designation(obj, command)
    kind = _label((obj.get("orbit_class") or {}).get("name"), "")
    return {"resolved": True, "designation": des,
            "name": _label(obj.get("shortname") or obj.get("fullname"), des), "kind": kind,
            "horizons": command}


def _curated(name: str) -> dict | None:
    s = name.casefold()
    for b in load_bodies():
        if s in (b.designation.casefold(), b.name.casefold(), b.slug):
            return {"resolved": True, "designation": b.designation, "name": b.name,
                    "kind": b.kind, "horizons": b.horizons}
    return None


class BodyResolver:
    """Name -> body answer, from the curated list or SBDB. Thread-safe, bounded cache."""

    def __init__(self, timeout_s: float, fetch: Fetch = http_fetch,
                 cache_size: int = CACHE_SIZE) -> None:
        self.timeout_s, self.fetch, self.cache_size = timeout_s, fetch, cache_size
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def peek(self, name: str) -> dict | None:
        """A curated or remembered answer, or None. Makes no upstream call."""
        found = _curated(name)
        if found is not None:
            return found
        key = name.casefold()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def __call__(self, name: str) -> dict:
        known = self.peek(name)
        if known is not None:
            return known
        try:
            data = json.loads(self.fetch(f"{SBDB_URL}?sstr={quote(name, safe='')}",
                                         self.timeout_s))
            answer = _from_sbdb(data if isinstance(data, dict) else {})
        except (requests.RequestException, OSError, ValueError) as exc:
            log.warning("SBDB lookup failed: %s", type(exc).__name__)
            return {"resolved": False, "unavailable": True, "message": SBDB_DOWN,
                    "did_you_mean": []}
        with self._lock:
            self._cache[name.casefold()] = answer
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return answer


@dataclass(frozen=True)
class BodyParams:
    """One body view request. `name` and `kind` are cosmetic; the key is the body's Horizons
    command, the SPHEREx frame index in use and the UTC day (data and ephemeris end there)."""

    designation: str
    name: str
    horizons: str
    kind: str
    index_tag: str
    day: str

    @property
    def key(self) -> str:
        body = {"body": self.horizons, "index": self.index_tag, "day": self.day,
                "v": PIPELINE_VERSION}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def body(self) -> Body:
        """The curated Body (with its blurb and composition) when listed, else a plain one."""
        for b in load_bodies():
            if b.horizons == self.horizons:
                return b
        return Body(designation=self.designation, name=self.name, horizons=self.horizons,
                    kind=self.kind)
