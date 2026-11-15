import pytest
import requests

from pxs.spherex import config
from pxs.spherex.net import BlockStore, TransientError, with_retries

DATA = bytes(range(256)) * 40  # 10240 bytes


class FakeBucket:
    def __init__(self, fail_first: int = 0) -> None:
        self.calls: list[tuple[int, int]] = []
        self.fail_first = fail_first

    def __call__(self, key: str, start: int, end: int) -> tuple[bytes, int]:
        self.calls.append((start, end))
        if len(self.calls) <= self.fail_first:
            raise TransientError("503")
        return DATA[start:end], len(DATA)


def test_reads_are_cached_and_coalesced(tmp_path) -> None:
    fake = FakeBucket()
    store = BlockStore(fetch=fake, root=tmp_path, block=1024)
    assert store.read("k", 100, 3000) == DATA[100:3000]
    assert fake.calls == [(0, 3072)]  # one coalesced run
    assert store.read("k", 500, 2500) == DATA[500:2500]
    assert len(fake.calls) == 1
    assert store.read("k", 10000, 10240) == DATA[10000:]  # short last block


def test_prefetch_fetches_only_missing_runs(tmp_path) -> None:
    fake = FakeBucket()
    store = BlockStore(fetch=fake, root=tmp_path, block=1024)
    store.prefetch("k", [(0, 10), (2048, 2100), (5000, 7000)])
    assert sorted(fake.calls)[1:] == [(2048, 3072), (4096, 7168)]  # runs fetch in parallel
    n = len(fake.calls)
    assert store.read("k", 4100, 7000) == DATA[4100:7000]
    assert len(fake.calls) == n


def test_cache_survives_a_new_store(tmp_path) -> None:
    BlockStore(fetch=FakeBucket(), root=tmp_path, block=1024).read("k", 0, 4000)
    fake = FakeBucket()
    assert BlockStore(fetch=fake, root=tmp_path, block=1024).read("k", 0, 4000) == DATA[:4000]
    assert fake.calls == []


def test_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(config, "BACKOFF_S", 0.0)
    attempts = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.ConnectionError("reset")
        return "ok"

    assert with_retries(flaky, "x", retries=4) == "ok"
    assert len(attempts) == 3


def test_gives_up_after_retries(monkeypatch) -> None:
    monkeypatch.setattr(config, "BACKOFF_S", 0.0)
    calls = []

    def down() -> None:
        calls.append(1)
        raise TransientError("503")

    with pytest.raises(TransientError):
        with_retries(down, "x", retries=2)
    assert len(calls) == 3


def test_non_transient_errors_are_not_retried() -> None:
    calls = []

    def missing() -> None:
        calls.append(1)
        raise requests.HTTPError("404")

    with pytest.raises(requests.HTTPError):
        with_retries(missing, "x")
    assert len(calls) == 1
