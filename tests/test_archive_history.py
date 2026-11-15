"""Saved archive checks: saving a run (day keys, sums, 30-day trim), the default and per-day
answers, and the read-only app (secret, ?day= validation, cache headers). No network, no Modal."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from pxs import archivehistory as h

DAY = 86400.0
T0 = 1_763_164_800.0  # 2025-11-15T00:00:00Z


def run(status: str, extra: str = "up") -> list[dict]:
    return [{"id": "gaia", "name": "ESA Gaia archive", "used_for": "Gaia stars", "backup": False,
             "status": status, "latency_ms": None if status == "down" else 420,
             "detail": "HTTP 503" if status == "down" else None},
            {"id": "sesame", "name": "CDS Sesame name lookup", "used_for": "names", "backup": False,
             "status": extra, "latency_ms": 90, "detail": None}]


def test_save_run_writes_today_sums_and_latest():
    store: dict = {}
    h.save_run(store, run("up"), T0 + 600)
    h.save_run(store, run("slow"), T0 + 900)
    h.save_run(store, run("down"), T0 + 1200)
    assert [s["s"]["gaia"] for s in store["day:2025-11-15"]] == ["up", "slow", "down"]
    assert store["day:2025-11-15"][2]["d"] == {"gaia": "HTTP 503"}
    assert store["day:2025-11-15"][0]["m"] == {"gaia": 420, "sesame": 90}
    assert store["index"]["days"]["2025-11-15"]["gaia"] == [3, 2, 1]
    assert store["latest"]["t"] == T0 + 1200


def test_save_run_keeps_thirty_days():
    store: dict = {}
    for i in range(h.DAYS + 3):
        h.save_run(store, run("up"), T0 + i * DAY + 60)
    days = sorted(store["index"]["days"])
    assert len(days) == h.DAYS and days[-1] == "2025-12-17"
    assert sorted(k for k in store if k.startswith("day:")) == [f"day:{d}" for d in days]


def test_default_answer_last_24_hours_and_days():
    store: dict = {}
    h.save_run(store, run("down"), T0 - DAY + 100)  # older than 24 h at `now`: in sums only
    h.save_run(store, run("up"), T0 + 3600)
    h.save_run(store, run("slow"), T0 + 7200)
    h.save_run(store, run("down"), T0 + 9000)
    now = T0 + 9100
    body = h.saved_status(store, now)
    assert body["checked_at"] == h.now_iso(T0 + 9000)
    c = body["checks"]
    assert c["times"] == [int(T0 + 3600), int(T0 + 7200), int(T0 + 9000)]
    assert c["archives"]["gaia"] == {"codes": "usd", "ms": [420, 420, None], "fail": {"2": "HTTP 503"}}
    assert body["days"]["dates"] == ["2025-11-14", "2025-11-15"]
    assert body["days"]["archives"]["gaia"] == [[1, 0, 0], [3, 2, 1]]
    g = body["history"]["gaia"]
    assert (g["checks"], g["answered"], g["since"], g["failed_last_hour"]) == (
        4, 2, "2025-11-14T00:00:00Z", 1)
    assert len(json.dumps(body)) < 4000


def test_empty_store_answers_no_checks():
    body = h.saved_status({}, T0)
    assert body["checked_at"] is None and body["archives"] == [] and body["days"]["dates"] == []


def test_valid_day():
    assert h.valid_day("2025-11-15") == "2025-11-15"
    for bad in ("2025-02-30", "2025-11-5", "x2025-11-15", "2025-11-15 ", "", "../index"):
        assert h.valid_day(bad) is None


def client(store, secret="s3cret", now=T0 + 9100):
    return TestClient(h.status_app(lambda: store, secret=secret, clock=lambda: now))


def test_app_needs_the_proxy_secret_and_is_cacheable():
    store: dict = {}
    h.save_run(store, run("up"), T0 + 60)
    c = client(store)
    denied = c.get("/api/archives")
    assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
    res = c.get("/api/archives", headers={h.SECRET_HEADER: "s3cret"})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, s-maxage=300, stale-while-revalidate=900"
    assert "set-cookie" not in res.headers and "vary" not in res.headers
    assert res.json()["archives"][0]["status"] == "up"


def test_non_ascii_secret_header_is_403_not_500():
    c = client({})
    res = c.get("/api/archives", headers={h.SECRET_HEADER.encode(): "s\u00e9cret\u2603".encode("utf-8")})
    assert res.status_code == 403 and res.headers["cache-control"] == "no-store"
    ok = c.get("/api/archives", headers={h.SECRET_HEADER: "s3cret"})
    assert ok.status_code == 200


def test_app_day_query():
    store: dict = {}
    h.save_run(store, run("down"), T0 - DAY + 100)
    h.save_run(store, run("up"), T0 + 60)
    c = client(store, secret="")
    past = c.get("/api/archives?day=2025-11-14")
    assert past.status_code == 200 and past.json()["checks"]["archives"]["gaia"]["codes"] == "d"
    assert past.headers["cache-control"] == h.PAST_DAY_CACHE
    today = c.get("/api/archives?day=2025-11-15")
    assert today.headers["cache-control"] == h.CACHE_CONTROL
    assert c.get("/api/archives?day=2025-10-01").status_code == 404
    for bad in ("day=2025-13-01", "day=index", "day=2025-11-15&day=2025-11-14", "other=1"):
        res = c.get(f"/api/archives?{bad}")
        assert res.status_code == 400 and res.headers["cache-control"] == "no-store"


def test_app_with_an_unreadable_store():
    def broken():
        raise RuntimeError("dict unavailable")
    res = TestClient(h.status_app(broken, secret="", clock=lambda: T0)).get("/api/archives")
    assert res.status_code == 200 and res.json()["checked_at"] is None
    assert res.headers["cache-control"] == "no-store"
