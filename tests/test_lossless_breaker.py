"""The breaker never costs data: searches with no equivalent fallback always run, with their
original timeouts; for Gaia and CatWISE it only starts the equivalent mirror at once."""

import time

import pytest
import requests

from pxs import catalogs, concurrency
from pxs.grid import Grid
from pxs.spherex import config as spx_config
from pxs.spherex import query
from pxs.wise import net


@pytest.fixture(autouse=True)
def _breakers():
    concurrency.reset_breakers()
    yield
    concurrency.reset_breakers()


class _Resp:
    status_code, content, text = 200, b"x\n", "x\n"

    def raise_for_status(self) -> None:
        return None


def test_wise_search_runs_even_when_irsa_just_failed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PXS_WISE_CACHE", str(tmp_path))
    concurrency.breaker("irsa").trip()
    seen = []
    monkeypatch.setattr(net._session, "request",
                        lambda m, u, **k: seen.append(k["timeout"]) or _Resp())
    assert net.get_text("https://irsa.example/SIA", {"POS": "1"}) == "x\n"
    assert seen == [net.QUERY_TIMEOUT_S]  # the timeout it always had


def test_spherex_sia_runs_even_when_irsa_just_failed_with_its_old_timeout(monkeypatch,
                                                                         tmp_path) -> None:
    monkeypatch.setenv("PXS_CACHE", str(tmp_path))
    concurrency.breaker("irsa").trip()
    seen = []

    class R:
        status_code, content = 200, b"<VOTABLE/>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(query.session(), "get", lambda *a, **k: seen.append(k["timeout"]) or R())
    assert query._sia_bytes("spherex_qr3", 1.0, 2.0, 0.001) == b"<VOTABLE/>"
    assert seen == [spx_config.SIA_TIMEOUT_S]  # one number: connect may take as long as before


def test_catalogue_queries_keep_their_old_timeout_and_are_never_skipped(monkeypatch) -> None:
    concurrency.breaker("gaia").trip()
    seen = []

    class R:
        text = "a\n"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(catalogs.requests, "post",
                        lambda url, **k: seen.append((url, k["timeout"])) or R())
    assert catalogs.tap_csv(catalogs.GAIA_TAP, "SELECT 1") == "a\n"
    assert seen == [(catalogs.GAIA_TAP, catalogs.TIMEOUT_S)]


def test_a_dead_primary_trips_its_breaker(monkeypatch) -> None:
    def dead(url, **k):
        raise requests.ConnectTimeout("no connect")

    monkeypatch.setattr(catalogs.requests, "post", dead)
    with pytest.raises(requests.ConnectTimeout):
        catalogs.tap_csv(catalogs.GAIA_TAP, "SELECT 1")
    assert concurrency.breaker("gaia").is_open()


def _timed_overlays(monkeypatch, tmp_path) -> dict[str, float]:
    started: dict[str, float] = {}
    t0 = time.monotonic()

    def fetch(url: str, adql: str) -> str:
        started.setdefault(url, time.monotonic() - t0)
        if url in (catalogs.GAIA_TAP, catalogs.IRSA_TAP):
            time.sleep(0.6)
            raise requests.ConnectTimeout("down")
        return ""

    monkeypatch.setattr(catalogs, "FALLBACK_AFTER_S", 0.5)
    catalogs.overlays(Grid(10.0, 20.0, 240.0, 240), fetch=fetch, cache_dir=tmp_path,
                      budget_s=2.0)
    return started


def test_with_the_breaker_closed_the_mirror_waits_its_usual_turn(monkeypatch, tmp_path) -> None:
    started = _timed_overlays(monkeypatch, tmp_path)
    assert started[catalogs.DATALAB_TAP] >= 0.45


def test_with_the_breaker_open_both_sources_are_asked_at_once(monkeypatch, tmp_path) -> None:
    concurrency.breaker("gaia").trip()
    concurrency.breaker("irsa").trip()
    started = _timed_overlays(monkeypatch, tmp_path)
    assert started[catalogs.GAIA_TAP] < 0.2 and started[catalogs.IRSA_TAP] < 0.2  # still asked
    assert started[catalogs.DATALAB_TAP] < 0.2
