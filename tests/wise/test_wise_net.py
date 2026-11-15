import pytest
import requests

from pxs.wise import net


class _Resp:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status_code, self.content, self.text = status, body, body.decode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _script(monkeypatch: pytest.MonkeyPatch, responses: list) -> list:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("headers")))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(net._session, "request", request)
    monkeypatch.setattr(net, "BACKOFF_S", 0.0)
    return calls


def test_range_read_retries_then_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "RETRIES", 3)  # the shipped value is lower; test the mechanism
    calls = _script(monkeypatch, [requests.ConnectionError("reset"), _Resp(503), _Resp(206, b"abc")])
    assert net.get_range("wise/x.fits", 10, 13) == b"abc"
    assert len(calls) == 3 and calls[-1][2] == {"Range": "bytes=10-12"}
    assert net.get_range("wise/x.fits", 10, 13) == b"abc"  # from disk, no new request
    assert len(calls) == 3
    assert (net.cache_root() / "s3" / "wise/x.fits.10-13").exists()


def test_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, [_Resp(503)] * (net.RETRIES + 1))
    with pytest.raises(requests.HTTPError):
        net.get_range("wise/y.fits", 0, 5)


def test_irsa_error_votable_raises_and_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, [_Resp(200, b"<?xml version='1.0'?><VOTABLE>ERROR</VOTABLE>"),
                          _Resp(200, b"a,b\n1,2\n")])
    with pytest.raises(ValueError):
        net.get_text("https://irsa/TAP", {"QUERY": "x"}, post=True)
    assert net.get_text("https://irsa/TAP", {"QUERY": "x"}, post=True) == "a,b\n1,2\n"


def test_user_agent_is_plain() -> None:
    assert net._session.headers["User-Agent"] == "planet-x-spherex"
    with pytest.raises(ValueError):
        net.get_range("k", 5, 5)
