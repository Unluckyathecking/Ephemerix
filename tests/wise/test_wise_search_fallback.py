"""WISE frames still come back when the TAP quality lookup, or one SIA phase, fails or is slow."""

import threading
import time

import pytest
import requests
from conftest import FIXTURES

from pxs.sources import collect_wise
from pxs.target import Target
from pxs.wise import net, search, visits

TAP_TABLES = {"allsky_4band_p1bm_frm", "allsky_3band_p1bm_frm", "allsky_2band_p1bm_frm",
              "neowiser_p1bm_frm"}


def _sia(params: dict) -> str:
    return (FIXTURES / f"sia_{params['COLLECTION']}.csv").read_text()


def _tap(params: dict) -> str:
    table = next(t for t in TAP_TABLES if f" FROM {t} " in params["QUERY"])
    return (FIXTURES / f"tap_{table}.csv").read_text()


def _fake(tap_behaviour):
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.SIA_URL:
            return _sia(params)
        return tap_behaviour(params)
    return fake


def test_tap_failure_keeps_every_sia_frame_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(params: dict) -> str:
        raise requests.HTTPError("HTTP 502 for https://irsa.ipac.caltech.edu/TAP/sync")

    monkeypatch.setattr(net, "get_text", _fake(down))
    frames = search.search_frames(248.167, 66.755, 0.002)
    sia = sum(len(search.parse_sia(_sia({"COLLECTION": p.sia_collection})))
              for p in search.PHASES)
    assert sia and len(frames) == sia
    assert all(f.qual_frame is None for f in frames)
    assert frames.warnings[0] == search.NO_QUALITY
    assert "2010 (three-band) failed" in frames.warnings[1]  # listed only by TAP
    assert frames.partial


def test_slow_tap_is_abandoned_at_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def hangs(params: dict) -> str:
        release.wait(5)
        return _tap(params)

    monkeypatch.setattr(net, "get_text", _fake(hangs))
    monkeypatch.setattr(search, "TAP_BUDGET_S", 0.2)
    start = time.monotonic()
    frames = search.search_frames(248.167, 66.755, 0.002)
    release.set()
    assert time.monotonic() - start < 2.0
    assert frames and frames.warnings[0] == search.NO_QUALITY


def test_tap_in_time_gives_quality_and_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "get_text", _fake(_tap))
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert frames.warnings == ()
    assert any(f.qual_frame is not None for f in frames)


def test_one_failed_sia_phase_loses_only_that_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.SIA_URL:
            if params["COLLECTION"] == "neowiser":
                raise requests.HTTPError("HTTP 502 for https://irsa.ipac.caltech.edu/SIA")
            return _sia(params)
        raise requests.HTTPError("HTTP 502 for https://irsa.ipac.caltech.edu/TAP/sync")

    monkeypatch.setattr(net, "get_text", fake)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert frames and {f.phase for f in frames} <= {"allsky", "postcryo"}
    assert frames.partial
    assert any("2013-2024 (NEOWISE) failed" in w for w in frames.warnings)


def test_tap_rows_stand_in_for_a_failed_sia_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.SIA_URL:
            raise requests.ConnectionError("reset")
        return _tap(params)

    monkeypatch.setattr(net, "get_text", fake)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert frames and all(f.qual_frame is not None for f in frames)
    assert frames.warnings == () and not frames.partial


def test_nothing_answering_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        raise requests.ConnectionError("reset")

    monkeypatch.setattr(net, "get_text", fake)
    with pytest.raises(RuntimeError):
        search.search_frames(248.167, 66.755, 0.002)


def test_hanging_tap_leaves_an_irsa_slot_for_required_queries(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PXS_WISE_CACHE", str(tmp_path))
    release = threading.Event()

    class Resp:
        status_code = 200

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def request(method, url, **kwargs):
        if url == search.TAP_URL:
            release.wait(5)
            return Resp(_tap({"QUERY": kwargs["data"]["QUERY"]}))
        return Resp(_sia(kwargs["params"]))

    monkeypatch.setattr(net._session, "request", request)
    monkeypatch.setattr(search, "TAP_BUDGET_S", 0.2)
    try:
        start = time.monotonic()
        frames = search.search_frames(248.167, 66.755, 0.002)
        assert frames and time.monotonic() - start < 2.0
        # The abandoned lookups still hang; a new required query must not wait for them.
        start = time.monotonic()
        net.get_text(search.SIA_URL, {"COLLECTION": "neowiser", "POS": "other"})
        assert time.monotonic() - start < 1.0
    finally:
        release.set()


def test_the_warning_reaches_the_view_and_marks_it_degraded(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def down(params: dict) -> str:
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(net, "get_text", _fake(down))

    class Wise:
        find_visits = staticmethod(visits.find_visits)

        @staticmethod
        def stack_visit(visit, band, grid):
            return None

    target = Target(name="t", ra=248.167, dec=66.755, epoch=2016.0, pmra_masyr=None,
                    pmdec_masyr=None)
    got = collect_wise(Wise(), target, grid=None)  # type: ignore[arg-type]
    assert search.NO_QUALITY in got.warnings
    assert got.failed is True  # three-band frames are missing; rebuild once TAP is back


def test_tap_uses_a_short_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.TAP_URL:
            seen.update(kwargs)
            return _tap(params)
        return _sia(params)

    monkeypatch.setattr(net, "get_text", fake)
    search.search_frames(248.167, 66.755, 0.002)
    assert seen == {"timeout": search.TAP_TIMEOUT_S, "retries": 0}
    assert search.TAP_TIMEOUT_S[1] <= 25.0


def test_quality_lost_but_every_phase_listed_is_not_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.SIA_URL:
            return _sia(params)
        if " FROM allsky_3band_p1bm_frm " in params["QUERY"]:
            return _tap(params)
        raise requests.HTTPError("HTTP 502 for https://irsa.ipac.caltech.edu/TAP/sync")

    monkeypatch.setattr(net, "get_text", fake)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert frames.warnings == (search.NO_QUALITY,) and not frames.partial
    assert any(f.phase == "3band" for f in frames)


def test_a_cached_tap_answer_does_not_wait_for_a_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "cached_text", lambda url, params: _tap(params))

    def no_network(*args, **kwargs):
        raise AssertionError("TAP went to the network despite a cached answer")

    monkeypatch.setattr(net, "get_text", lambda url, params, **kw:
                        _sia(params) if url == search.SIA_URL else no_network())
    held = [search._tap_slots() for _ in range(search.IRSA_OPTIONAL_MAX)]
    for h in held:
        h.__enter__()  # every optional slot taken, as by stalled lookups of another build
    try:
        frames = search.search_frames(248.167, 66.755, 0.002)
    finally:
        for h in held:
            h.__exit__(None, None, None)
    assert frames.warnings == () and any(f.qual_frame is not None for f in frames)
