"""build_lists takes the three-band phase from TAP, else the bucket, else the timing rule."""

from __future__ import annotations

import pytest
from wise_frames import build_lists, threeband

from pxs.wise.frames import Frame

F = Frame("3band", "07110a", 2, "W2", 55414.7, ((0.0, 0.0),) * 4)


def test_tap_wins_when_it_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threeband, "bucket_frames", lambda *a: pytest.fail("bucket read"))
    frames, info = build_lists._threeband([F], 1.0, 2.0, 0.03, [], [])
    assert frames == [F] and info["how"] == "IRSA TAP"


def test_the_bucket_lists_the_phase_when_tap_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threeband, "bucket_frames", lambda *a: [F])
    frames, info = build_lists._threeband(None, 1.0, 2.0, 0.03, [], [])
    assert frames == [F] and info == {"status": "complete", "how": threeband.HOW, "frames": 1}


def test_timing_decides_when_the_bucket_fails_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threeband, "bucket_frames", lambda *a: None)
    frames, info = build_lists._threeband(None, 1.0, 2.0, 0.03, [], [])
    assert frames is None and info["status"] == "missing"
