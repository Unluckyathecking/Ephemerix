"""Concurrency helpers: errors surface, nothing hangs, and IRSA sees at most four queries."""

import threading
import time

import pytest

from pxs import catalogs, concurrency
from pxs.grid import Grid
from pxs.wise import net


class Stop(BaseException):
    """Stands in for pxs.api.progress.BuildCancelled (also a BaseException)."""


def test_map_ordered_keeps_input_order() -> None:
    assert concurrency.map_ordered(lambda x: x * x, [3, 1, 2], workers=3) == [9, 1, 4]


@pytest.mark.parametrize("exc", [ValueError("bad"), Stop()])
def test_map_ordered_raises_the_worker_error_without_waiting_for_the_rest(exc) -> None:
    release = threading.Event()

    def fn(x: int) -> int:
        if x == 0:
            raise exc
        release.wait(5)  # the others would block for 5 s if the call waited for them
        return x

    start = time.monotonic()
    with pytest.raises(type(exc)):
        concurrency.map_ordered(fn, [0, 1, 2, 3], workers=2)
    release.set()
    assert time.monotonic() - start < 2.0


def test_background_delivers_results_and_errors() -> None:
    assert concurrency.background(lambda a, b: a + b, 2, 3).result(timeout=2) == 5
    with pytest.raises(ZeroDivisionError):
        concurrency.background(lambda: 1 / 0).result(timeout=2)


def test_irsa_queries_never_exceed_four_at_once(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path) -> None:
    monkeypatch.setenv("PXS_WISE_CACHE", str(tmp_path))
    lock, live, peak = threading.Lock(), [0], [0]

    class Resp:
        status_code, text = 200, "a\n1\n"

        def raise_for_status(self) -> None:
            return None

    def slow(*args, **kwargs) -> Resp:
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return Resp()

    monkeypatch.setattr(net._session, "request", slow)
    threads = [threading.Thread(target=net.get_text,
                                args=("https://irsa.ipac.caltech.edu/SIA", {"POS": str(i)}))
               for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert 1 < peak[0] <= concurrency.IRSA_MAX_CONCURRENT


def test_catalogues_return_within_the_budget_when_an_archive_hangs(tmp_path) -> None:
    release = threading.Event()

    def fetch(url: str, adql: str) -> str:
        if url == catalogs.IRSA_TAP:
            release.wait(5)
        return "source_id,ra,dec,pmra,pmdec,phot_g_mean_mag\n"

    start = time.monotonic()
    ov, warn = catalogs.overlays(Grid(10.0, 5.0, 240.0, 240), fetch=fetch, cache_dir=tmp_path,
                                 budget_s=0.2)
    release.set()
    assert time.monotonic() - start < 2.0
    assert ov["catwise"] == [] and warn == [("CatWISE2020 sources could not be fetched, so none "
                                            "are marked.")]
