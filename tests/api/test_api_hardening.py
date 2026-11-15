"""Hardening: build slots, degraded views, client keys, resolve limits, cache budget, names."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from api_helpers import Q, build_now, eventually, wait_for, write_view

from pxs.api import params as params_mod
from pxs.api.app import client_address
from pxs.api.cache import ViewCache
from pxs.api.degraded import is_degraded
from pxs.api.jobs import JobManager
from pxs.api.params import parse_view
from pxs.api.progress import BuildCancelled, Tracker
from pxs.api.ratelimit import RateLimiter, client_key
from pxs.api.resolve import Resolver
from pxs.api.sweep import sweep


class StuckBuild:
    """Blocks without ever reporting (like a hung network call) for dec == 1."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def __call__(self, params, out: Path, report):
        if params.dec == 1.0:
            self.release.wait(20)
        return write_view(out, params)


def q(dec: str) -> dict:
    return {**Q, "dec": dec}


# ---- H2: slots, abandoned threads ------------------------------------------------------

def test_slot_is_released_at_timeout_while_the_build_stays_blocked(make_client) -> None:
    build = StuckBuild()
    client, _ = make_client(build=build, build_timeout_s=0.2, max_builds=1, queue_cap=0,
                            rate_limit=50)
    try:
        a = client.get("/api/view", params=q("1")).json()
        assert wait_for(client, a["status_url"], {"error"})["state"] == "error"
        # the only slot is free again even though the first build thread is still blocked
        assert build_now(client, q("2"))["state"] == "done"
        assert client.get("/api/health").json()["jobs"]["abandoned"] == 1
    finally:
        build.release.set()


def test_abandoned_cap_flips_health_and_refuses_new_builds(make_client) -> None:
    build = StuckBuild()
    client, _ = make_client(build=build, build_timeout_s=0.2, max_builds=3, max_abandoned=1,
                            rate_limit=50)
    try:
        a = client.get("/api/view", params=q("1")).json()
        wait_for(client, a["status_url"], {"error"})
        h = client.get("/api/health")
        assert h.status_code == 503 and h.json()["status"] == "unhealthy"
        assert client.get("/api/view", params=q("5")).status_code == 503
    finally:
        build.release.set()
    # the thread ends; healthy again
    assert eventually(lambda: client.get("/api/health").status_code == 200)


def test_last_resort_exit_is_opt_in(tmp_path: Path) -> None:
    exits: list[int] = []
    build = StuckBuild()
    jobs = JobManager(ViewCache(tmp_path, 10**6), build, max_builds=1, queue_cap=0,
                      timeout_s=0.1, max_abandoned=1, exit_when_stuck=True, exit_grace_s=0.1,
                      exit_fn=exits.append)
    try:
        jobs.submit(parse_view(q("1").items()))
        assert eventually(lambda: exits == [1])
    finally:
        build.release.set()
        jobs.close()
    quiet: list[int] = []
    off_build = StuckBuild()
    off = JobManager(ViewCache(tmp_path / "b", 10**6), off_build, max_builds=1, queue_cap=0,
                     timeout_s=0.1, max_abandoned=1, exit_grace_s=0.05, exit_fn=quiet.append)
    try:
        off.submit(parse_view(q("1").items()))
        assert eventually(lambda: not off.healthy())  # stuck at the cap, as above
        time.sleep(0.3)  # only lengthens the window in which a wrongly armed timer would fire
        assert quiet == []  # the watchdog is off by default
    finally:
        off_build.release.set()
        off.close()


def test_exit_is_skipped_when_the_service_recovered(tmp_path: Path) -> None:
    exits: list[int] = []
    build = StuckBuild()
    jobs = JobManager(ViewCache(tmp_path, 10**6), build, max_builds=1, queue_cap=0,
                      timeout_s=0.1, max_abandoned=1, exit_when_stuck=True, exit_grace_s=3600,
                      exit_fn=exits.append)
    jobs.submit(parse_view(q("1").items()))
    assert eventually(lambda: not jobs.healthy())
    build.release.set()  # the stuck thread ends
    assert eventually(jobs.healthy)
    jobs._exit_if_still_stuck()  # what the timer runs at the end of the grace period
    assert exits == []
    jobs.close()


def test_deadline_stops_a_build_at_its_next_report() -> None:
    now = [0.0]
    t = Tracker(clock=lambda: now[0])
    t.deadline = 5.0
    t.report("stage", 0.1)
    now[0] = 5.0
    with pytest.raises(BuildCancelled):
        t.report("stage", 0.2)
    assert t.cancelled.is_set()


# ---- M3: degraded views ----------------------------------------------------------------

def test_degraded_manifest_signal() -> None:
    assert is_degraded({"degraded": True, "warnings": []})
    flag_wins = {"degraded": False,
                 "warnings": ["Gaia sources could not be fetched, so none are marked."]}
    assert not is_degraded(flag_wins)
    for w in ("Gaia sources could not be fetched, so none are marked.",
              "WISE images could not be loaded; the archive did not answer.",
              "SPHEREx data could not be loaded; the archive did not answer.",
              "3 WISE stacks failed and are left out.",
              "2 SPHEREx stacks or spectra failed and are left out."):
        assert is_degraded({"warnings": [w]}), w
    assert not is_degraded({"warnings": ["No WISE visits were found at this position.",
                                         "WISE images are not available in this build."]})


class FixedBuild:
    def __init__(self, **flags) -> None:
        self.flags = flags

    def __call__(self, params, out: Path, report):
        m = write_view(out, params)
        m.update(self.flags)
        (out / "manifest.json").write_text(json.dumps(m))
        return m


def test_degraded_view_is_no_store_and_expires_while_good_stays_long_cached(make_client) -> None:
    client, _ = make_client(build=FixedBuild(degraded=True), degraded_ttl_s=600)
    done = build_now(client, Q)
    assert done["state"] == "done"
    hit = client.get("/api/view", params=Q)
    assert hit.status_code == 200 and hit.headers["cache-control"] == "no-store"
    f = client.get(done["manifest_url"])
    assert f.status_code == 200 and f.headers["cache-control"] == "no-store"
    cache = client.app.state.cache
    cache._clock = lambda: time.time() + 1000  # past the expiry, without sleeping
    assert client.get(done["manifest_url"]).status_code == 404  # expired
    assert client.get("/api/view", params=Q).status_code == 202  # a retry rebuilds

    good, _ = make_client(build=FixedBuild(degraded=False))
    done = build_now(good, q("7"))  # another position: the cache directory is shared
    assert good.get("/api/view", params=q("7")).headers["cache-control"] == "public, max-age=86400"
    assert "immutable" in good.get(done["manifest_url"]).headers["cache-control"]


def test_degraded_expiry_survives_a_restart(tmp_path: Path) -> None:
    now = [100.0]
    cache = ViewCache(tmp_path, 10**6, degraded_ttl_s=60, clock=lambda: now[0])
    p = parse_view(Q.items())
    work = cache.work_dir(p.key, "j")
    write_view(work, p)
    cache.commit(p.key, work, degraded=True)
    again = ViewCache(tmp_path, 10**6, degraded_ttl_s=60, clock=lambda: now[0])
    assert again.has(p.key) and again.is_degraded(p.key)
    now[0] = 161.0
    assert not again.has(p.key)


def test_a_degraded_view_never_evicts_a_good_one(tmp_path: Path) -> None:
    cache = ViewCache(tmp_path, max_bytes=2500, degraded_ttl_s=600)
    good = []
    for dec in ("1", "2"):
        p = parse_view(q(dec).items())
        w = cache.work_dir(p.key, "j")
        write_view(w, p, extra_bytes=1000)
        cache.commit(p.key, w)
        good.append(p.key)
    bad = parse_view(q("3").items())
    w = cache.work_dir(bad.key, "j")
    write_view(w, bad, extra_bytes=1000)
    cache.commit(bad.key, w, degraded=True)
    assert all(cache.has(k) for k in good) and cache.has(bad.key)  # overshoots, evicts nothing
    p = parse_view(q("4").items())  # a new good view evicts the degraded one first
    w = cache.work_dir(p.key, "j")
    write_view(w, p, extra_bytes=1000)
    cache.commit(p.key, w)
    assert not cache.has(bad.key) and cache.has(p.key)


# ---- H1: client identity ---------------------------------------------------------------

def test_client_key_collapses_ipv6_and_normalises_mapped_ipv4() -> None:
    assert client_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:2:1::9") == client_key("2001:db8:1:2:ffff::1")
    assert client_key("2001:db8:1:3::1") != client_key("2001:db8:1:2::1")
    assert client_key("::ffff:203.0.113.9") == "203.0.113.9" == client_key("203.0.113.9")
    assert client_key("testclient") == "testclient"
    assert len(client_key("x" * 500)) == 64


def test_client_address_applies_the_key_to_both_sources() -> None:
    class Req:
        def __init__(self, host: str, xff: str = "") -> None:
            self.client = type("C", (), {"host": host})()
            self.headers = {"x-forwarded-for": xff} if xff else {}

    assert client_address(Req("2001:db8::1"), False) == "2001:db8::/64"
    assert client_address(Req("::ffff:10.0.0.1"), False) == "10.0.0.1"
    assert client_address(Req("1.1.1.1", "9.9.9.9, 2001:db8:0:0:5::7"), True) == "2001:db8::/64"


def test_health_counts_distinct_clients_without_naming_them(make_client) -> None:
    client, build = make_client(queue_cap=10)
    build.release.set()
    client.get("/api/view", params=q("1"))
    client.get("/api/view", params=q("2"))
    h = client.get("/api/health")
    assert h.json()["clients"] == {"build": 1, "resolve": 0}
    assert "testclient" not in h.text
    t = [0.0]
    rl = RateLimiter(1, 10.0, clock=lambda: t[0])
    rl.try_acquire("a")
    rl.try_acquire("b")
    rl.try_acquire("b")  # refused, still counted as seen
    assert rl.clients_seen() == 2
    t[0] = 11.0
    assert rl.clients_seen() == 0


# ---- M1: resolve -----------------------------------------------------------------------

def test_resolve_is_limited_and_cached_answers_are_free(make_client) -> None:
    calls: list[str] = []

    def fetch(url: str, timeout: float) -> str:
        calls.append(url)
        return "<Sesame/>"

    client, _ = make_client(resolver=Resolver(1.0, fetch), resolve_limit=2)
    for name in ("A one", "B two"):
        assert client.get("/api/resolve", params={"name": name}).status_code == 200
    r = client.get("/api/resolve", params={"name": "C three"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert len(calls) == 2  # the refused request never reached the upstream
    again = client.get("/api/resolve", params={"name": "a ONE"})
    assert again.status_code == 200 and len(calls) == 2  # cache hit: no quota, no upstream


def test_resolve_cache_is_bounded() -> None:
    r = Resolver(1.0, lambda url, t: "<Sesame/>", cache_size=3)
    for i in range(10):
        r(f"name {i}")
    assert len(r._cache) == 3
    assert r.peek("name 9") is not None and r.peek("name 0") is None


# ---- M2: upstream cache budget ---------------------------------------------------------

def test_sweep_removes_oldest_files_to_the_budget(tmp_path: Path) -> None:
    a, b = tmp_path / "wise", tmp_path / "catalogs"
    a.mkdir()
    b.mkdir()
    files = []
    for i, d in enumerate((a, b, a, b)):
        f = d / f"f{i}"
        f.write_bytes(b"x" * 100)
        os.utime(f, (1000 + i, 1000 + i))
        files.append(f)
    assert sweep([a, b, tmp_path / "missing"], 250) == 200
    assert [f.exists() for f in files] == [False, False, True, True]
    assert sweep([a, b], 250) == 0


def test_cache_is_swept_after_each_build(tmp_path: Path, make_client) -> None:
    up = tmp_path / "upstream"
    up.mkdir()
    (up / "old").write_bytes(b"x" * 5000)
    client, build = make_client(upstream_cache_dirs=(up,), upstream_cache_max_bytes=1000)
    build.release.set()
    assert build_now(client, Q)["state"] == "done"
    assert eventually(lambda: not (up / "old").exists())
    assert not (up / "old").exists()


# ---- pipeline version and names --------------------------------------------------------

def test_pipeline_version_is_part_of_the_cache_key(monkeypatch) -> None:
    before = parse_view(Q.items()).key
    monkeypatch.setattr(params_mod, "PIPELINE_VERSION", "2")
    assert parse_view(Q.items()).key != before


def test_health_reports_pipeline_version(make_client) -> None:
    client, _ = make_client()
    assert client.get("/api/health").json()["pipeline"] == params_mod.PIPELINE_VERSION


def test_named_request_keeps_its_name_on_the_200_and_job_paths(make_client) -> None:
    client, build = make_client()
    build.release.set()
    named = {**Q, "name": "Barnard's star"}
    first = client.get("/api/view", params=named)
    assert first.status_code == 202
    status = wait_for(client, first.json()["status_url"], {"done"})
    m = client.get(status["manifest_url"]).json()
    assert m["target"]["name"] == "Barnard's star"
    assert client.get("/api/view", params=named).json()["target"]["name"] == "Barnard's star"
    # a different name for the same view is served its own name, not the first one's
    assert client.get("/api/view", params={**Q, "name": "Other"}).json()["target"]["name"] == "Other"
    other_url = status["manifest_url"].split("?")[0] + "?name=Other"
    assert client.get(other_url).json()["target"]["name"] == "Other"
    assert client.get(status["manifest_url"].split("?")[0]).json()["target"]["name"] is None


def test_unnamed_status_url_is_plain(make_client) -> None:
    client, _ = make_client()
    r = client.get("/api/view", params=Q).json()
    assert r["status_url"] == f"/api/jobs/{r['job']}"


def test_a_build_that_stops_at_its_own_deadline_still_fails_the_job(tmp_path: Path) -> None:
    now = [0.0]

    def build(params, out: Path, report):
        now[0] = 1000.0  # the deadline passes while the build runs
        report("next stage", 0.5)  # raises BuildCancelled: the thread ends before the join
        raise AssertionError("not reached")

    jobs = JobManager(ViewCache(tmp_path, 10**6), build, max_builds=1, queue_cap=0,
                      timeout_s=30.0, clock=lambda: now[0])
    try:
        job, _ = jobs.submit(parse_view(Q.items()))
        assert eventually(lambda: job.state == "error")
        assert "longer than 30 s" in job.error
        assert jobs.active(job.params.key) is None and jobs.abandoned_count() == 0
    finally:
        jobs.close()
