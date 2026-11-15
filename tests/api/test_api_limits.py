import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api_helpers import Q, build_now, wait_for, write_view

from pxs.api.cache import ViewCache
from pxs.api.params import parse_view
from pxs.api.ratelimit import RateLimiter
from pxs.api.resolve import Resolver, parse_sesame


def test_rate_limit_on_build_starts_only(make_client) -> None:
    client, build = make_client(rate_limit=2, queue_cap=10)
    build.release.set()
    for dec in ("1", "2"):
        assert client.get("/api/view", params={**Q, "dec": dec}).status_code == 202
    r = client.get("/api/view", params={**Q, "dec": "3"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0 and r.json()["retry_after_s"] > 0
    # another client is not affected
    other = client.get("/api/view", params={**Q, "dec": "4"},
                       headers={"X-Forwarded-For": "203.0.113.9"})
    assert other.status_code == 429  # XFF is ignored unless PXS_TRUST_PROXY=1


def test_cached_views_are_not_rate_limited(make_client) -> None:
    client, build = make_client(rate_limit=1)
    build.release.set()
    assert build_now(client, Q)["state"] == "done"
    for _ in range(5):
        assert client.get("/api/view", params=Q).status_code == 200


def test_trusted_proxy_uses_rightmost_forwarded_address(make_client) -> None:
    client, _ = make_client(rate_limit=1, trust_proxy=True, queue_cap=10)
    h = {"X-Forwarded-For": "1.1.1.1, 198.51.100.7"}
    assert client.get("/api/view", params={**Q, "dec": "1"}, headers=h).status_code == 202
    spoof = {"X-Forwarded-For": "9.9.9.9, 198.51.100.7"}
    assert client.get("/api/view", params={**Q, "dec": "2"}, headers=spoof).status_code == 429
    h2 = {"X-Forwarded-For": "198.51.100.8"}
    assert client.get("/api/view", params={**Q, "dec": "3"}, headers=h2).status_code == 202


def test_rate_limiter_window_slides_and_refunds() -> None:
    t = [0.0]
    rl = RateLimiter(2, 10.0, clock=lambda: t[0])
    assert rl.try_acquire("a") == 0 and rl.try_acquire("a") == 0
    assert rl.try_acquire("a") == 10 and rl.try_acquire("b") == 0
    rl.refund("a")
    assert rl.try_acquire("a") == 0
    t[0] = 10.5
    assert rl.try_acquire("a") == 0


def test_concurrent_acquires_admit_at_most_the_limit() -> None:
    rl = RateLimiter(6, 600.0)
    barrier = threading.Barrier(64)

    def go(_: int) -> int:
        barrier.wait()
        return rl.try_acquire("203.0.113.1")

    with ThreadPoolExecutor(64) as pool:
        results = list(pool.map(go, range(64)))
    assert results.count(0) == 6


def test_concurrent_build_starts_from_one_client_admit_at_most_the_limit(make_client) -> None:
    client, build = make_client(rate_limit=3, queue_cap=100, max_builds=1)

    def start(i: int) -> int:
        return client.get("/api/view", params={**Q, "dec": str(i)}).status_code

    with ThreadPoolExecutor(24) as pool:
        codes = list(pool.map(start, range(24)))
    assert codes.count(202) == 3 and codes.count(429) == 21
    build.release.set()


def test_refused_and_joined_requests_do_not_use_up_the_limit(make_client) -> None:
    client, build = make_client(rate_limit=2, max_builds=1, queue_cap=0)
    first = client.get("/api/view", params={**Q, "dec": "1"})
    assert first.status_code == 202
    assert build.started.wait(5)
    for _ in range(3):  # queue full: 503, refunded
        assert client.get("/api/view", params={**Q, "dec": "2"}).status_code == 503
    for _ in range(3):  # joining the running job never counts
        assert client.get("/api/view", params={**Q, "dec": "1"}).status_code == 202
    build.release.set()
    wait_for(client, first.json()["status_url"], {"done"})
    assert client.get("/api/view", params={**Q, "dec": "3"}).status_code == 202  # 2nd of 2
    assert client.get("/api/view", params={**Q, "dec": "4"}).status_code == 429


def test_queue_cap_answers_503(make_client) -> None:
    client, build = make_client(max_builds=1, queue_cap=1)
    assert client.get("/api/view", params={**Q, "dec": "1"}).status_code == 202
    assert build.started.wait(5)
    assert client.get("/api/view", params={**Q, "dec": "2"}).status_code == 202
    r = client.get("/api/view", params={**Q, "dec": "3"})
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    # joining an existing job still works while the queue is full
    assert client.get("/api/view", params={**Q, "dec": "2"}).status_code == 202


def test_cors_allows_only_configured_origins(make_client) -> None:
    client, _ = make_client()
    ok = client.get("/api/health", headers={"Origin": "https://site.example"})
    assert ok.headers["access-control-allow-origin"] == "https://site.example"
    assert "retry-after" in ok.headers["access-control-expose-headers"].lower()
    bad = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    pre = client.options("/api/view", headers={"Origin": "https://site.example",
                                               "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400
    assert client.post("/api/view", params=Q).status_code == 405


def test_path_traversal_is_refused(make_client) -> None:
    client, build = make_client()
    build.release.set()
    key = build_now(client, Q)["manifest_url"].split("/")[3]
    for path in (f"/api/views/{key}/../../../pyproject.toml",
                 f"/api/views/{key}/%2e%2e/%2e%2e/config.py",
                 f"/api/views/{key}/frames/..%2F..%2Fmanifest.json",
                 f"/api/views/{key}/frames/x.txt",
                 "/api/views/..%2F..%2Fetc/passwd",
                 f"/api/views/{key.upper()}/manifest.json",
                 "/api/views/tmp/manifest.json"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "root" not in r.text


def test_cache_eviction_respects_the_cap(tmp_path: Path) -> None:
    cache = ViewCache(tmp_path, max_bytes=2500)
    keys = []
    for dec in ("1", "2", "3"):
        p = parse_view({**Q, "dec": dec}.items())
        if len(keys) == 2:  # view 1 was used more recently than view 2
            os.utime(cache.views / keys[0], (2000, 2000))
            os.utime(cache.views / keys[1], (1000, 1000))
        work = cache.work_dir(p.key, "job")
        write_view(work, p, extra_bytes=1000)
        cache.commit(p.key, work)
        keys.append(p.key)
    assert cache.stats()["bytes"] <= 2500
    assert cache.has(keys[0]) and cache.has(keys[2]) and not cache.has(keys[1])
    assert ViewCache(tmp_path, max_bytes=2500).stats()["views"] == 2  # rescanned on start


def test_health(make_client) -> None:
    client, _ = make_client()
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["jobs"] == {"running": 0, "queued": 0, "abandoned": 0}
    assert set(h["sources"]) == {"wise", "spherex"} and h["cache"]["views"] == 0


SESAME = """<?xml version="1.0"?><Sesame><Target><name>Barnard</name>
<Resolver name="S=Simbad"><oname>NAME Barnard's star</oname>
<jradeg>269.45207695</jradeg><jdedeg>4.69339088</jdedeg>
<pm><pmRA>-801.551</pmRA><pmDE>10362.394</pmDE></pm></Resolver></Target></Sesame>"""


def test_resolve_success_and_soft_failure(make_client) -> None:
    calls = []

    def fetch(url: str, timeout: float) -> str:
        calls.append(url)
        if "Nowhere" in url:
            return "<Sesame><Target><INFO>not found</INFO></Target></Sesame>"
        if "Flaky" in url:
            raise TimeoutError("cds down")
        return SESAME

    client, _ = make_client(resolver=Resolver(1.0, fetch))
    ok = client.get("/api/resolve", params={"name": "Barnard's star"}).json()
    assert ok["resolved"] and abs(ok["pmdec"] - 10362.394) < 1e-6 and ok["epoch"] == 2000.0
    assert calls[0].startswith("https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?Barnard%27s")
    client.get("/api/resolve", params={"name": "barnard's STAR"})
    assert len(calls) == 1  # cached
    for name in ("Nowhere", "Flaky"):
        r = client.get("/api/resolve", params={"name": name})
        assert r.status_code == 200 and r.json() == {
            "resolved": False, "message": "Could not resolve that name. Enter the coordinates "
                                          "instead."}
    assert client.get("/api/resolve", params={"name": "a/../b?c=d#"}).status_code == 422
    assert client.get("/api/resolve").status_code == 422
    assert parse_sesame("<Sesame/>") is None
