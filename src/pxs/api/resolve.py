"""Object-name lookup through CDS Sesame. Fails soft: any problem gives "could not resolve".

The host and path are fixed here; the user's name is only URL-quoted into the query.
The XML comes only from that fixed host; Python's expat does not fetch external entities
and limits entity expansion (expat >= 2.4.1), so the stdlib parser is used.
"""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import quote

import requests

log = logging.getLogger("pxs.api.resolve")

SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV"
USER_AGENT = "planet-x-spherex/0.1 (NASA Space Apps 2026)"
CACHE_SIZE = 512
NOT_FOUND = "Could not resolve that name. Enter the coordinates instead."

Fetch = Callable[[str, float], str]


MAX_BODY = 1_000_000  # bytes; a Sesame answer is a few KB


def http_fetch(url: str, timeout_s: float) -> str:
    with requests.get(url, timeout=timeout_s, headers={"User-Agent": USER_AGENT},
                      stream=True) as res:
        res.raise_for_status()
        body = res.raw.read(MAX_BODY + 1, decode_content=True)
        if len(body) > MAX_BODY:
            raise ValueError("resolver answer too large")
        return body.decode(res.encoding or "utf-8", errors="replace")


def _float(node: ET.Element, tag: str) -> float | None:
    found = node.find(tag)
    try:
        return float(found.text) if found is not None and found.text else None
    except ValueError:
        return None


def parse_sesame(xml_text: str) -> dict | None:
    """Position and proper motion from the first resolver that found the object."""
    root = ET.fromstring(xml_text)
    for res in root.iter("Resolver"):
        ra, dec = _float(res, "jradeg"), _float(res, "jdedeg")
        if ra is None or dec is None:
            continue
        pm = res.find("pm")
        pmra = _float(pm, "pmRA") if pm is not None else None
        pmdec = _float(pm, "pmDE") if pm is not None else None
        if pmra is None or pmdec is None:
            pmra = pmdec = None
        oname = res.find("oname")
        return {"resolved": True, "name": oname.text if oname is not None else None,
                "ra": ra, "dec": dec, "epoch": 2000.0 if pmra is not None else None,
                "pmra": pmra, "pmdec": pmdec, "source": "CDS Sesame"}
    return None


class Resolver:
    """Caches answers (including misses) so repeated lookups do not hit CDS."""

    def __init__(self, timeout_s: float, fetch: Fetch = http_fetch,
                 cache_size: int = CACHE_SIZE) -> None:
        self.timeout_s, self.fetch, self.cache_size = timeout_s, fetch, cache_size
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def peek(self, name: str) -> dict | None:
        """The remembered answer for `name`, or None. Makes no upstream call."""
        key = name.casefold()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def __call__(self, name: str) -> dict:
        key = name.casefold()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        try:
            found = parse_sesame(self.fetch(f"{SESAME_URL}?{quote(name, safe='')}",
                                            self.timeout_s))
        except (requests.RequestException, OSError, ET.ParseError, ValueError) as exc:
            # network, HTTP or XML problem: a soft failure, and not cached
            log.warning("Sesame lookup failed: %s", type(exc).__name__)
            return {"resolved": False, "message": NOT_FOUND}
        answer = found or {"resolved": False, "message": NOT_FOUND}
        with self._lock:
            self._cache[key] = answer
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return answer
