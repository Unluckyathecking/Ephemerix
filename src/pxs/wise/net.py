"""HTTP access for the WISE package: one shared session, retries with backoff, and an on-disk
cache under ``cache/wise/`` (override with the ``PXS_WISE_CACHE`` environment variable).

The cache is safe to delete at any time. Entries are written to a temporary file and renamed,
so concurrent workers never see a half-written file. Byte ranges are keyed by S3 key and range;
IRSA query results by a hash of the URL and parameters.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import requests

from pxs.concurrency import irsa_slot

log = logging.getLogger(__name__)

USER_AGENT = "planet-x-spherex"
BUCKET_URL = "https://nasa-irsa-wise.s3.amazonaws.com/"  # us-west-2, anonymous
# Worst case for one call: 2 attempts x (5 s connect + 15 s read) + 1 s backoff = 41 s. A
# read timeout is per socket read, so a slow-drip body can run longer; the build deadline
# and the job runner's abandon-at-timeout cover that.
RETRIES = 1
BACKOFF_S = 1.0
TIMEOUT_S = (5.0, 15.0)  # connect, read
# IRSA searches (SIA, and the TAP frame-quality lookup) routinely take 10-25 s to answer, so
# they get a longer read timeout than byte-range reads. Worst case for one query:
# 2 attempts x (5 s + 60 s) + 1 s backoff = 131 s, still inside the build limit.
QUERY_TIMEOUT_S = (5.0, 60.0)
_RETRY_STATUS = {429, 500, 502, 503, 504}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
_session.mount("https://", _adapter)


def cache_root() -> Path:
    """Directory holding the WISE cache (``cache/wise`` relative to the working directory)."""
    return Path(os.environ.get("PXS_WISE_CACHE", "cache/wise"))


def _read_cache(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_cache(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, path)


def _request(method: str, url: str, *, timeout: tuple[float, float] = TIMEOUT_S,
             retries: int | None = None,
             slot: Callable[[], AbstractContextManager[None]] | None = None,
             **kwargs) -> requests.Response:
    """One HTTP request with retries on connection errors, timeouts, 429 and 5xx. `slot`,
    if given, is held for each attempt, never across a backoff."""
    retries = RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        try:
            with slot() if slot is not None else nullcontext():
                resp = _session.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code not in _RETRY_STATUS:
                resp.raise_for_status()
                return resp
            error: Exception = requests.HTTPError(f"HTTP {resp.status_code} for {url}")
        except (requests.ConnectionError, requests.Timeout) as exc:
            error = exc
        if attempt < retries:
            delay = BACKOFF_S * 2**attempt
            log.debug("retry %d for %s in %.1f s: %s", attempt + 1, url, delay, error)
            time.sleep(delay)
    raise error


def get_range(key: str, start: int, stop: int, *, cache: bool = True) -> bytes:
    """Bytes ``[start, stop)`` of an object in s3://nasa-irsa-wise, cached on disk unless
    ``cache`` is false (the thousands of one-off header probes of ``bucketsearch``)."""
    if not (0 <= start < stop):
        raise ValueError(f"bad byte range {start}-{stop}")
    path = cache_root() / "s3" / f"{key}.{start}-{stop}"
    cached = _read_cache(path) if cache else None
    if cached is not None:
        return cached
    resp = _request("GET", BUCKET_URL + key, headers={"Range": f"bytes={start}-{stop - 1}"})
    payload = resp.content
    if cache:
        _write_cache(path, payload)
    return payload


def _query_path(url: str, params: Mapping[str, str]) -> Path:
    blob = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    return cache_root() / "irsa" / (hashlib.sha1(blob.encode()).hexdigest() + ".csv")


def cached_text(url: str, params: Mapping[str, str]) -> str | None:
    """The cached answer of an IRSA query, or None; never touches the network."""
    cached = _read_cache(_query_path(url, params))
    return None if cached is None else cached.decode()


def get_text(url: str, params: Mapping[str, str], *, post: bool = False,
             timeout: tuple[float, float] = QUERY_TIMEOUT_S, retries: int | None = None) -> str:
    """Text of an IRSA query (GET, or POST form for TAP), cached on disk by URL and params.

    IRSA reports query errors as HTTP 200 with a VOTable body; those raise ``ValueError``
    and are not cached. At most ``concurrency.IRSA_MAX_CONCURRENT`` queries run at once in
    this process (held per attempt, not during a retry's backoff); ``timeout`` and
    ``retries`` override the defaults for one call. There is no circuit breaker here: these
    searches have no equivalent fallback, so every lookup tries them.
    """
    path = _query_path(url, params)
    cached = _read_cache(path)
    if cached is not None:
        return cached.decode()
    common = {"timeout": timeout, "retries": retries, "slot": irsa_slot}
    if post:
        resp = _request("POST", url, data=dict(params), **common)
    else:
        resp = _request("GET", url, params=dict(params), **common)
    text = resp.text
    if text.lstrip().startswith("<?xml"):
        raise ValueError(f"IRSA query failed: {text[:300]}")
    _write_cache(path, text.encode())
    return text
