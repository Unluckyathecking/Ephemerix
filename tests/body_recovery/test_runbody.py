"""run() writes one JSON-ready record per variant, also when the body fails (offline)."""

from __future__ import annotations

import json

from solarsystem_validation import runbody

from pxs.solarsystem.horizons import EphemPoint, HorizonsError
from pxs.solarsystem.track import Track, Visit
from pxs.spherex.types import Frame

BODY = {"pdes": "136108", "name": "Haumea", "cls": "TNO", "H": 0.14}


def test_horizons_failure_writes_an_error_record_per_variant(monkeypatch):
    def boom(command, stop):
        raise HorizonsError("no ephemeris")

    monkeypatch.setattr(runbody, "find_visits", boom)
    out: dict[str, dict] = {}
    status = runbody.run(BODY, 61300.0, runbody.VARIANTS, {"git": "x"},
                         lambda v, r: out.__setitem__(v, r))
    assert set(out) == set(runbody.VARIANTS) and set(status.values()) == {"error"}
    rec = out["real"]
    assert rec["error"]["kind"] == "horizons" and rec["error"]["stage"] == "track"
    json.dumps(rec, allow_nan=False)


def test_short_passes_are_skipped_not_measured(monkeypatch):
    eph = EphemPoint(60900.0, 10.0, 0.0, 1.0, 1.0, 17.0, 50.0, 49.0, 95.0, 1.0)
    visits = tuple(Visit(Frame("spherex_dr1", f"o{i}", 1, 60900.0 + i * 0.01, f"k{i}",
                               0.75, 1.1), eph) for i in range(3))
    track = Track(visits, (eph,), 0, 0)
    monkeypatch.setattr(runbody, "find_visits", lambda c, s: track)
    monkeypatch.setattr(runbody, "analyse_pass", lambda *a, **k: None)
    out: dict[str, dict] = {}
    runbody.run(BODY, 61300.0, ["real", "off_ra"], {}, lambda v, r: out.__setitem__(v, r))
    assert out["real"]["status"] == "ok" and out["real"]["passes"] == []
    assert out["real"]["skipped"][0]["n_frames"] == 3
    assert out["off_ra"]["track"]["n_visits"] == 3
