"""Build the SPHEREx frame index from the public bucket s3://nasa-irsa-spherex.

For every Level-2 file under <release>/level2/<week>/ it reads only the leading header
bytes (one ranged GET), parses the WCS and times with pxs.spherex.indexfmt, and writes
Parquet shards under OUT/rows/release=<r>/week=<w>/part-<hash>.parquet. Re-running skips
keys already in a shard, so it is resumable, idempotent and incremental. Unreadable files
are counted and listed in OUT/failed/<release>/<week>.json, never fatal.

    python tools/spherex_index/build_index.py OUT [--week dr1/2025W17_4B] [--count]

Releases come from pxs.spherex.config.COLLECTIONS (a new release is one edit there).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

from pxs.spherex import config
from pxs.spherex.indexfmt import (
    HEADER_RANGE_BYTES,
    SCHEMA,
    SCHEMA_VERSION,
    HeaderTruncated,
    UnreadableFrame,
    parse_frame,
    rows_to_table,
)

log = logging.getLogger("spherex_index")
BASE = config.BUCKET_URL
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
UA = "planet-x-spherex-index-builder"
MAX_HEADER_RANGE = 1 << 20
CHUNK_KEYS = 2000


def releases() -> tuple[str, ...]:
    """Release prefixes in the bucket, from the configured collections (spherex_dr1 -> dr1)."""
    return tuple(c.removeprefix("spherex_") for c in config.COLLECTIONS)


class RateLimiter:
    """Spaces calls at most `rps` per second across threads."""

    def __init__(self, rps: float) -> None:
        self._gap = 1.0 / rps
        self._next = time.monotonic()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self._gap
        if at > now:
            time.sleep(at - now)


@dataclass
class Counters:
    """Network and outcome counts of one run; additive."""

    requests: int = 0
    bytes_read: int = 0
    retries: int = 0
    widened: int = 0
    rows: int = 0
    failed: int = 0
    skipped: int = 0
    max_header_bytes: int = 0
    seconds: float = 0.0


class Fetcher:
    """Ranged GETs and listings against the public bucket, rate limited, with backoff."""

    def __init__(self, max_rps: float, counters: Counters) -> None:
        self.limiter = RateLimiter(max_rps)
        self.c = counters
        self._local = threading.local()
        self._lock = threading.Lock()

    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = UA
            self._local.s = s
        return s

    def _get(self, url: str, **kw: object) -> requests.Response:
        for attempt in range(6):
            self.limiter.wait()
            try:
                r = self._session().get(url, timeout=30, **kw)  # type: ignore[arg-type]
                with self._lock:
                    self.c.requests += 1
                    self.c.bytes_read += len(r.content)
                if r.status_code in (200, 206):
                    return r
                if r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                err: Exception = RuntimeError(f"HTTP {r.status_code}")
            except (requests.ConnectionError, requests.Timeout) as e:
                err = e
            with self._lock:
                self.c.retries += 1
            delay = min(30.0, 0.5 * 2**attempt) * (1 + random.random() / 2)
            log.info("retry %d for %s in %.1fs: %s", attempt + 1, url[-60:], delay, err)
            time.sleep(delay)
        raise RuntimeError(f"gave up on {url[-80:]}")

    def list_prefix(self, prefix: str, delimiter: str | None = None) -> tuple[list[tuple[str, int]], list[str]]:
        """(objects as (key, size), common prefixes) under `prefix`, following pagination."""
        objs: list[tuple[str, int]] = []
        prefixes: list[str] = []
        token = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if delimiter:
                params["delimiter"] = delimiter
            if token:
                params["continuation-token"] = token
            root = ET.fromstring(self._get(BASE, params=params).content)
            for c in root.findall("s3:Contents", NS):
                objs.append((c.findtext("s3:Key", namespaces=NS) or "",
                             int(c.findtext("s3:Size", namespaces=NS) or 0)))
            for p in root.findall("s3:CommonPrefixes", NS):
                prefixes.append(p.findtext("s3:Prefix", namespaces=NS) or "")
            if root.findtext("s3:IsTruncated", namespaces=NS) != "true":
                return objs, prefixes
            token = root.findtext("s3:NextContinuationToken", namespaces=NS)

    def header_row(self, key: str, size: int) -> dict:
        """Index row for one file: one ranged GET, widened only if the header is longer."""
        n = HEADER_RANGE_BYTES
        while True:
            data = self._get(BASE + key, headers={"Range": f"bytes=0-{n - 1}"}).content
            try:
                row = parse_frame(key, size, data)
            except HeaderTruncated:
                if n >= min(MAX_HEADER_RANGE, size):
                    raise
                n *= 4
                with self._lock:
                    self.c.widened += 1
                continue
            with self._lock:
                self.c.max_header_bytes = max(self.c.max_header_bytes, len(data))
            return row


def list_weeks(f: Fetcher, release: str) -> list[str]:
    """Week directory names under <release>/level2/."""
    _, prefixes = f.list_prefix(f"{release}/level2/", "/")
    return sorted(p.rstrip("/").rsplit("/", 1)[1] for p in prefixes)


def list_fits(f: Fetcher, release: str, week: str) -> list[tuple[str, int]]:
    """(key, size) of every .fits file of a week directory."""
    objs, _ = f.list_prefix(f"{release}/level2/{week}/")
    return sorted(o for o in objs if o[0].endswith(".fits"))


def week_dir(root: Path, release: str, week: str) -> Path:
    return root / "rows" / f"release={release}" / f"week={week}"


def indexed_keys(root: Path, release: str, week: str) -> set[str]:
    """Keys already in this week's shards (only the key column is read)."""
    d = week_dir(root, release, week)
    out: set[str] = set()
    for p in sorted(d.glob("part-*.parquet")):
        out.update(pq.read_table(p, columns=["key"]).column("key").to_pylist())
    return out


def write_part(root: Path, release: str, week: str, rows: list[dict]) -> Path:
    """Write rows as one content-addressed shard (same keys, same file name)."""
    d = week_dir(root, release, week)
    d.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1("\n".join(sorted(r["key"] for r in rows)).encode()).hexdigest()[:16]
    path = d / f"part-{name}.parquet"
    tmp = d / f".{path.name}.tmp"
    pq.write_table(rows_to_table(sorted(rows, key=lambda r: r["key"])), tmp, compression="zstd")
    tmp.replace(path)
    return path


def write_failures(root: Path, release: str, week: str, failures: list[dict]) -> None:
    path = root / "failed" / release / f"{week}.json"
    if failures:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(failures, indent=1))
    elif path.exists():
        path.unlink()


def index_week(root: Path, release: str, week: str, *, max_rps: float = 25.0, workers: int = 6,
               chunk: int = CHUNK_KEYS, limit: int | None = None, on_chunk=None) -> Counters:
    """Index the new files of one week directory. Returns the run's counters."""
    t0 = time.monotonic()
    c = Counters()
    fetch = Fetcher(max_rps, c)
    listing = list_fits(fetch, release, week)
    have = indexed_keys(root, release, week)
    todo = [o for o in listing if o[0] not in have]
    c.skipped = len(listing) - len(todo)
    if limit:
        todo = todo[:limit]
    failures: list[dict] = []
    def one(obj: tuple[str, int]) -> dict | dict[str, str]:
        try:
            return fetch.header_row(*obj)
        except (UnreadableFrame, RuntimeError, requests.RequestException) as e:
            return {"failed": obj[0], "error": f"{type(e).__name__}: {e}"}

    for start in range(0, len(todo), chunk):
        with ThreadPoolExecutor(max_workers=workers) as ex:
            out = list(ex.map(one, todo[start:start + chunk]))
        rows = [r for r in out if "failed" not in r]
        failures.extend({"key": r["failed"], "error": r["error"]} for r in out if "failed" in r)
        if rows:
            write_part(root, release, week, rows)
            c.rows += len(rows)
        if on_chunk:
            on_chunk()
    c.failed = len(failures)
    if not limit:
        write_failures(root, release, week, failures)
    c.seconds = time.monotonic() - t0
    log.info("%s/%s: %d new rows, %d skipped, %d failed, %.0f s, %d requests",
             release, week, c.rows, c.skipped, c.failed, c.seconds, c.requests)
    return c


def write_manifest(root: Path, code_version: str) -> dict:
    """Scan the shards and write OUT/manifest.json (row counts per release and week)."""
    per: dict[str, dict[str, dict]] = {}
    total_bytes = 0
    mjd = {}
    for p in sorted((root / "rows").glob("release=*/week=*/part-*.parquet")):
        rel = p.parent.parent.name.split("=", 1)[1]
        wk = p.parent.name.split("=", 1)[1]
        meta = pq.ParquetFile(p).metadata
        w = per.setdefault(rel, {}).setdefault(wk, {"rows": 0, "parts": 0})
        w["rows"] += meta.num_rows
        w["parts"] += 1
        total_bytes += p.stat().st_size
        col = pq.read_table(p, columns=["mjd"]).column("mjd")
        lo, hi = float(pc.min(col).as_py()), float(pc.max(col).as_py())
        a, b = mjd.get(rel, (lo, hi))
        mjd[rel] = (min(a, lo), max(b, hi))
    failed = {}
    for p in sorted((root / "failed").glob("*/*.json")):
        failed.setdefault(p.parent.name, {})[p.stem] = len(json.loads(p.read_text()))
    manifest = {
        "schema_version": SCHEMA_VERSION, "code_version": code_version,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bucket": config.BUCKET, "releases_configured": list(releases()),
        "releases": {r: {"rows": sum(w["rows"] for w in ws.values()), "weeks": len(ws),
                         "mjd_min": mjd[r][0], "mjd_max": mjd[r][1], "per_week": ws,
                         "failed": sum(failed.get(r, {}).values())}
                     for r, ws in per.items()},
        "rows": sum(w["rows"] for ws in per.values() for w in ws.values()),
        "failed": sum(sum(v.values()) for v in failed.values()),
        "bytes_on_disk": total_bytes, "columns": SCHEMA.names,
    }
    tmp = root / ".manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1))
    tmp.replace(root / "manifest.json")
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--week", action="append", help="release/week, e.g. dr1/2025W17_4B (repeatable)")
    ap.add_argument("--max-rps", type=float, default=25.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, help="index at most N new files per week (testing)")
    ap.add_argument("--count", action="store_true", help="only list and count files")
    ap.add_argument("--code-version", default=os.environ.get("PXS_CODE_VERSION", "dev"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    f = Fetcher(a.max_rps, Counters())
    pairs = ([tuple(w.split("/", 1)) for w in a.week] if a.week
             else [(r, w) for r in releases() for w in list_weeks(f, r)])
    if a.count:
        with ThreadPoolExecutor(max_workers=8) as ex:
            sizes = list(ex.map(lambda p: list_fits(f, *p), pairs))
        n = sum(len(s) for s in sizes)
        log.info("%d weeks, %d files, %.1f TB", len(pairs), n, sum(o[1] for s in sizes for o in s) / 1e12)
        return
    for rel, wk in pairs:
        index_week(a.out, rel, wk, max_rps=a.max_rps, workers=a.workers, limit=a.limit)
    m = write_manifest(a.out, a.code_version)
    log.info("manifest: %d rows, %d failed", m["rows"], m["failed"])


if __name__ == "__main__":
    main()
