"""The site's proxy: a shared secret proves a request came through it, and only then is
its x-pxs-client-ip header used as the client address."""

from __future__ import annotations

import pytest
from api_helpers import Q

from pxs.api.app import NOT_PROXIED, client_address
from pxs.api.config import ConfigError, from_env

SECRET = "s3cr3t-" + "a" * 40
PROXY = {"x-pxs-proxy-secret": SECRET}


def via(ip: str, secret: str = SECRET) -> dict:
    return {"x-pxs-proxy-secret": secret, "x-pxs-client-ip": ip}


class Req:
    def __init__(self, headers: dict, host: str = "10.0.0.1") -> None:
        self.client = type("C", (), {"host": host})()
        self.headers = headers


def test_client_address_trusts_the_header_only_with_the_secret() -> None:
    assert client_address(Req(via("203.0.113.7")), False, SECRET) == "203.0.113.7"
    assert client_address(Req(via("2001:db8::5")), False, SECRET) == "2001:db8::/64"
    assert client_address(Req(via("203.0.113.7", "wrong")), False, SECRET) == "10.0.0.1"
    assert client_address(Req({"x-pxs-client-ip": "203.0.113.7"}), False, SECRET) == "10.0.0.1"
    # no secret configured: the header means nothing
    assert client_address(Req(via("203.0.113.7")), False) == "10.0.0.1"


def test_with_a_secret_forwarded_headers_are_never_read() -> None:
    xff = {"x-forwarded-for": "9.9.9.9, 198.51.100.7", "x-vercel-forwarded-for": "9.9.9.9"}
    assert client_address(Req(xff), True, SECRET) == "10.0.0.1"
    assert client_address(Req({**xff, **PROXY}), True, SECRET) == "10.0.0.1"  # no client ip
    assert client_address(Req(xff), True) == "198.51.100.7"  # unchanged without a secret


@pytest.mark.parametrize("bad", ["", "not-an-ip", "1.2.3.4, 5.6.7.8", "999.1.1.1", "é"])
def test_malformed_client_ip_falls_back_to_the_peer(bad: str) -> None:
    assert client_address(Req(via(bad)), False, SECRET) == "10.0.0.1"


def test_non_ascii_secret_header_does_not_crash() -> None:
    assert client_address(Req(via("203.0.113.7", "sécret")), False, SECRET) == "10.0.0.1"


def test_correct_secret_gives_each_client_its_own_bucket(make_client) -> None:
    client, build = make_client(rate_limit=1, queue_cap=10, proxy_secret=SECRET)
    build.release.set()
    assert client.get("/api/view", params={**Q, "dec": "1"},
                      headers=via("203.0.113.1")).status_code == 202
    assert client.get("/api/view", params={**Q, "dec": "2"},
                      headers=via("203.0.113.1")).status_code == 429
    assert client.get("/api/view", params={**Q, "dec": "3"},
                      headers=via("203.0.113.2")).status_code == 202
    assert client.get("/api/health", headers=PROXY).json()["clients"]["build"] == 2


def test_spoofed_client_ip_without_the_secret_has_no_effect(make_client) -> None:
    client, build = make_client(rate_limit=1, queue_cap=10, proxy_secret=SECRET)
    build.release.set()
    assert client.get("/api/view", params={**Q, "dec": "1"},
                      headers={"x-pxs-client-ip": "203.0.113.1"}).status_code == 202
    for i, h in enumerate(({"x-pxs-client-ip": "203.0.113.9"}, via("203.0.113.9", "wrong"),
                           {"X-Forwarded-For": "203.0.113.9"})):
        r = client.get("/api/view", params={**Q, "dec": str(2 + i)}, headers=h)
        assert r.status_code == 429, h  # all one bucket: the socket peer


def test_require_proxy_refuses_requests_without_the_secret(make_client) -> None:
    client, _ = make_client(proxy_secret=SECRET, require_proxy=True)
    for h in ({}, {"x-pxs-proxy-secret": "wrong"}, {"x-pxs-proxy-secret": SECRET[:-1]}):
        for path in ("/api/view", "/api/resolve", "/api/jobs/x", "/api/views/k/a.png",
                     "/api/nope"):
            r = client.get(path, params=Q, headers=h)
            assert r.status_code == 403, (path, h)
            assert r.json() == {"error": NOT_PROXIED}
            assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/view", params=Q, headers=PROXY).status_code == 202


def test_health_without_the_secret_is_minimal(make_client) -> None:
    client, _ = make_client(proxy_secret=SECRET, require_proxy=True)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    full = client.get("/api/health", headers=PROXY).json()
    assert {"status", "version", "clients", "jobs"} <= set(full)
    # without REQUIRE, health is unchanged for everyone
    open_client, _ = make_client(proxy_secret=SECRET)
    assert "clients" in open_client.get("/api/health").json()


def test_require_off_serves_requests_without_the_secret(make_client) -> None:
    client, _ = make_client(proxy_secret=SECRET)
    assert client.get("/api/view", params=Q).status_code == 202


def test_secret_is_never_echoed(make_client) -> None:
    client, build = make_client(rate_limit=1, queue_cap=10, proxy_secret=SECRET,
                                require_proxy=True)
    build.release.set()
    responses = [
        client.get("/api/view", params=Q, headers=via("203.0.113.1")),
        client.get("/api/view", params={**Q, "dec": "9"}, headers=via("203.0.113.1")),  # 429
        client.get("/api/view", params={"ra": "x"}, headers=PROXY),  # 422
        client.get("/api/view", params=Q),  # 403
        client.get("/api/view", params=Q, headers={"x-pxs-proxy-secret": "wrong"}),
        client.get("/api/health"),
        client.get("/api/health", headers=PROXY),
        client.get("/api/missing", headers=PROXY),
    ]
    for r in responses:
        assert SECRET not in r.text and SECRET not in str(r.headers), r.status_code
    assert SECRET not in repr(client.app.state)


def test_settings_read_the_secret_and_keep_it_out_of_repr() -> None:
    s = from_env({"PXS_PROXY_SECRET": f" {SECRET} ", "PXS_REQUIRE_PROXY": "1"})
    assert s.proxy_secret == SECRET and s.require_proxy
    assert SECRET not in repr(s)
    assert from_env({}).proxy_secret == "" and not from_env({}).require_proxy


@pytest.mark.parametrize("env", [
    {"PXS_REQUIRE_PROXY": "1"},  # required but no secret
    {"PXS_PROXY_SECRET": "short"},
    {"PXS_PROXY_SECRET": "x" * 31},
])
def test_settings_reject_unusable_proxy_config(env: dict) -> None:
    with pytest.raises(ConfigError) as exc:
        from_env(env)
    assert "short" not in str(exc.value) and "x" * 31 not in str(exc.value)
