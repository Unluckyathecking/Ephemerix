"""The saved archive checks and the tiny read-only app that serves them. Written with Claude Code.

The scheduled `archive_watch` job (deploy/modal_app.py) probes the archives every 5 minutes
(`pxs.api.archivestatus.run_probes`) and saves the run with `save_run()` into a dict-like store
(a modal.Dict in production):

- "latest": the newest run in full, {"t", "archives"}.
- "day:YYYY-MM-DD": that UTC day's checks, [{"t", "s": {id: status}, "m": {id: ms}, "d": {id: detail}}].
- "index": {"days": {"YYYY-MM-DD": {id: [checks, answered, slow]}}}, the per-day sums.

Each run rewrites only today's day key, the index and "latest"; days older than DAYS are
deleted. `archive_status` serves the store through `status_app()` and probes nothing. This
module imports no pipeline code, so that function starts in moments on the smallest container.

`GET /api/archives` answers `{checked_at, archives, history, checks, days}`: the newest run,
per-archive counts for the site's notes (`history`), every check of the last 24 hours (`checks`,
compact, below) and the per-day sums of the last DAYS days (`days`: `dates` oldest first and per
archive one [checks, answered, slow] per date). `GET /api/archives?day=YYYY-MM-DD` answers
`{day, checks}` with that day's checks. Compact checks: `times` (Unix seconds, oldest first) and
per archive `codes` (one letter per time: "u" answering, "s" slow, "d" not answering, "-" not
checked), `ms` (response time or null) and `fail` (failure detail by index). Answers are the same
for every visitor and carry a CDN cache header: 5 minutes, or a month for a finished day.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import time
from collections.abc import Callable, MutableMapping, Sequence
from datetime import UTC, date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

DAYS = 30
RECENT_S = 3600  # "failed in the last hour"
WINDOW_S = 24 * 3600  # every check of this long is in the default answer
CACHE_CONTROL = "public, s-maxage=300, stale-while-revalidate=900"
PAST_DAY_CACHE = "public, s-maxage=2592000, immutable"  # a finished day never changes
NO_STORE = {"Cache-Control": "no-store"}
SECRET_HEADER = "x-pxs-proxy-secret"  # the same shared secret the site's proxy sends
CODES = {"up": "u", "slow": "s", "down": "d"}
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

Store = MutableMapping  # a dict, or a modal.Dict (get, [], pop)


def now_iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def day_of(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).date().isoformat()


def sample_of(results: Sequence[dict], t: float) -> dict:
    return {"t": t, "s": {r["id"]: r["status"] for r in results},
            "m": {r["id"]: r["latency_ms"] for r in results if r.get("latency_ms") is not None},
            "d": {r["id"]: r["detail"] for r in results if r.get("detail")}}


def save_run(store: Store, results: Sequence[dict], t: float) -> None:
    """Append this run to today's key, add it to the day sums, drop days older than DAYS."""
    today = day_of(t)
    store[f"day:{today}"] = [*(store.get(f"day:{today}") or []), sample_of(results, t)]
    days = dict((store.get("index") or {}).get("days") or {})
    sums = {aid: list(v) for aid, v in (days.get(today) or {}).items()}
    for r in results:
        c = sums.setdefault(r["id"], [0, 0, 0])
        c[0], c[1], c[2] = c[0] + 1, c[1] + (r["status"] != "down"), c[2] + (r["status"] == "slow")
    days[today] = sums
    oldest = (date.fromisoformat(today) - timedelta(days=DAYS - 1)).isoformat()
    for d in [d for d in days if d < oldest]:
        days.pop(d)
        if f"day:{d}" in store:
            store.pop(f"day:{d}")
    store["index"] = {"days": days}
    store["latest"] = {"t": t, "archives": list(results)}


def compact(samples: Sequence[dict]) -> dict:
    """Checks in the compact shape (see the module docstring), oldest first."""
    rows = sorted((s for s in samples if isinstance(s, dict) and "t" in s), key=lambda s: s["t"])
    ids = sorted({aid for s in rows for aid in (s.get("s") or {})})
    per = {aid: {"codes": "".join(CODES.get((s.get("s") or {}).get(aid), "-") for s in rows),
                 "ms": [(s.get("m") or {}).get(aid) for s in rows],
                 "fail": {str(i): d for i, s in enumerate(rows) if (d := (s.get("d") or {}).get(aid))}}
           for aid in ids}
    return {"times": [int(s["t"]) for s in rows], "archives": per}


def _history(days: dict, recent: Sequence[dict], now: float) -> dict[str, dict]:
    """Per archive over the days held: checks, answered, the first day, failures in the last hour."""
    out: dict[str, dict] = {}
    for d in sorted(days):
        for aid, (checks, answered, _slow) in days[d].items():
            row = out.setdefault(aid, {"checks": 0, "answered": 0, "since": f"{d}T00:00:00Z",
                                       "failed_last_hour": 0})
            row["checks"] += checks
            row["answered"] += answered
    for s in recent:
        if s["t"] >= now - RECENT_S:
            for aid, status in (s.get("s") or {}).items():
                if status == "down" and aid in out:
                    out[aid]["failed_last_hour"] += 1
    return out


def saved_status(store: Store, now: float) -> dict:
    """The default answer for /api/archives; empty when nothing has been saved yet."""
    latest = store.get("latest") or {}
    if not isinstance(latest.get("t"), (int, float)):
        return {"checked_at": None, "archives": [], "history": {},
                "checks": {"times": [], "archives": {}}, "days": {"dates": [], "archives": {}}}
    days = (store.get("index") or {}).get("days") or {}
    keys = {day_of(now - WINDOW_S), day_of(now)}
    recent = [s for k in sorted(keys) for s in (store.get(f"day:{k}") or []) if s["t"] >= now - WINDOW_S]
    dates = sorted(days)[-DAYS:]
    ids = sorted({aid for d in dates for aid in days[d]})
    return {"checked_at": now_iso(latest["t"]), "archives": list(latest.get("archives") or []),
            "history": _history(days, recent, now), "checks": compact(recent),
            "days": {"dates": dates,
                     "archives": {aid: [days[d].get(aid, [0, 0, 0]) for d in dates] for aid in ids}}}


def valid_day(raw: str) -> str | None:
    """`raw` if it is a real YYYY-MM-DD date, else None."""
    if not DAY_RE.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def status_app(read: Callable[[], Store], secret: str | None = None,
               clock: Callable[[], float] = time.time) -> FastAPI:
    """The read-only app. With a secret (PXS_PROXY_SECRET by default) only the proxy is served."""
    secret = os.environ.get("PXS_PROXY_SECRET", "") if secret is None else secret
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def error(message: str, status: int) -> JSONResponse:
        return JSONResponse({"error": message}, status, headers=NO_STORE)

    @app.get("/api/archives")
    def archives(request: Request) -> JSONResponse:
        if secret and not hmac.compare_digest(
                request.headers.get(SECRET_HEADER, "").encode("utf-8"), secret.encode("utf-8")):
            return error("This service answers only through the project site.", 403)
        raw = request.query_params.getlist("day")
        if len(raw) > 1 or (raw and valid_day(raw[0]) is None) or set(request.query_params) - {"day"}:
            return error("Give at most one day, as YYYY-MM-DD.", 400)
        now = clock()
        try:
            store = read()
            if raw:
                samples = store.get(f"day:{raw[0]}")
                if not samples:
                    return error("No checks are saved for that day.", 404)
                cache = CACHE_CONTROL if raw[0] >= day_of(now) else PAST_DAY_CACHE
                return JSONResponse({"day": raw[0], "checks": compact(samples)},
                                    headers={"Cache-Control": cache})
            body = saved_status(store, now)
        except Exception:  # say "not checked" (and do not cache that) rather than fail
            log.warning("archive checks could not be read", exc_info=True)
            return JSONResponse(saved_status({}, now), headers=NO_STORE)
        return JSONResponse(body, headers={"Cache-Control": CACHE_CONTROL})

    return app
