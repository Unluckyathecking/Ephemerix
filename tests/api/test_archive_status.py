"""Archive uptime probes: classification and order. No network: the HTTP layer is stubbed."""

from __future__ import annotations

import requests

from pxs.api import archivestatus as st

TAP = next(a for a in st.ARCHIVES if a.id == "irsa_tap")
S3 = next(a for a in st.ARCHIVES if a.id == "wise_s3")


class Res:
    def __init__(self, code: int = 200, text: str = "table_name\nx\n") -> None:
        self.status_code, self.text = code, text


def ticking(*times: float):
    it = iter(times)
    return lambda: next(it)


def run(archive, outcome, times=(0.0, 0.2)) -> dict:
    def request(_a):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return st.classify(archive, request, clock=ticking(*times))


def test_classify_up_slow_down():
    up = run(TAP, Res())
    assert (up["status"], up["latency_ms"], up["detail"]) == ("up", 200, None)
    assert run(TAP, Res(), (0.0, st.SLOW_S + 1))["status"] == "slow"
    down = run(TAP, Res(502))
    assert (down["status"], down["latency_ms"], down["detail"]) == ("down", None, "HTTP 502")


def test_classify_failures_are_plain():
    assert run(TAP, Res(200, "<VOTABLE>error</VOTABLE>"))["detail"] == "error answer"
    assert run(TAP, requests.ReadTimeout("x"))["detail"] == "no answer within 10 s"
    assert run(TAP, requests.ConnectTimeout("x"))["detail"] == "could not connect within 5 s"
    assert run(TAP, requests.ConnectionError("secret.host"))["detail"] == "could not connect"
    assert run(TAP, ValueError("https://x?key=1"))["detail"] == "ValueError"
    assert run(S3, Res(403))["status"] == "up"  # the bucket answered; listing is private


def test_run_probes_keeps_order_and_fields():
    out = st.run_probes(request=lambda a: Res())
    assert [r["id"] for r in out] == [a.id for a in st.ARCHIVES]
    assert set(out[0]) == {"id", "name", "used_for", "backup", "status", "latency_ms", "detail"}


