"""Breaker: remembers for a while that a service just failed; an answer clears it."""

import pytest
import requests

from pxs import concurrency
from pxs.concurrency import Breaker


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_a_new_breaker_is_closed() -> None:
    assert not Breaker("irsa", cooldown_s=60, clock=Clock()).is_open()


def test_a_trip_lasts_for_the_cooldown() -> None:
    clock = Clock()
    b = Breaker("irsa", cooldown_s=60, clock=clock)
    b.trip()
    assert b.is_open()
    clock.t += 59
    assert b.is_open()
    clock.t += 2
    assert not b.is_open()


def test_an_answer_closes_it() -> None:
    b = Breaker("irsa", cooldown_s=60, clock=Clock())
    b.trip()
    b.reset()
    assert not b.is_open()


@pytest.mark.parametrize("exc, trips", [
    (requests.ConnectTimeout(), True),
    (requests.ReadTimeout(), True),
    (requests.ConnectionError(), True),
    (requests.HTTPError("HTTP 502"), False),
    (ValueError("TAP query failed"), False),
])
def test_unreachable_tells_a_dead_service_from_a_bad_answer(exc, trips) -> None:
    assert concurrency.unreachable(exc) is trips


def test_a_read_timeout_can_be_declared_routine() -> None:
    assert not concurrency.unreachable(requests.ReadTimeout(), read_timeout_counts=False)
    assert concurrency.unreachable(requests.ConnectTimeout(), read_timeout_counts=False)


def test_breakers_are_shared_per_name_and_reset_for_tests() -> None:
    a = concurrency.breaker("irsa")
    assert concurrency.breaker("irsa") is a
    assert concurrency.breaker("gaia") is not a
    a.trip()
    concurrency.reset_breakers()
    assert not concurrency.breaker("irsa").is_open()
