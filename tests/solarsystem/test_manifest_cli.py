"""The body manifest validates against docs/api.md schema 1 and carries the extension."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pxs.manifest import validate
from pxs.solarsystem import __main__ as cli
from pxs.solarsystem import bodymanifest, pipeline
from pxs.solarsystem.bodies import Body
from pxs.solarsystem.controls import Control
from pxs.solarsystem.phot import BANDS, BandFlux
from pxs.solarsystem.stacks import read_half
from pxs.solarsystem.track import Track, Visit
from pxs.spherex.types import Pass

from .conftest import eph, frame, make_stamp

RA0, DEC0 = 221.0, 13.7
BODY = Body("136108", "Haumea", "136108;", "dwarf planet", "Icy and fast-spinning.",
            "crystalline water ice", "test ref")


def _read(n: int = 10):
    out = []
    for i in range(n):
        mjd = 61000.0 + 0.5 * i
        ra = RA0 + i * 15.0 / 3600 / np.cos(np.radians(DEC0))
        wave = 0.8 + 0.12 * i  # spans b1 to b3
        v = Visit(frame(mjd, key=f"k{i}"), eph(mjd, ra, DEC0))
        out.append((v, make_stamp(ra, DEC0, mjd, wave, 0.5, half=read_half(), seed=i)))
    return out


@pytest.fixture
def run(monkeypatch) -> pipeline.BodyRun:
    read = _read()
    monkeypatch.setattr(pipeline, "read_visits", lambda visits, half: (read, 0))
    zero = tuple(BandFlux(b, 20, 0.001, 0.0005) for b in BANDS)
    monkeypatch.setattr(pipeline, "run_control", lambda v, h: Control(zero, (), 8, 40))
    visits = tuple(v for v, _ in read)
    monkeypatch.setattr(pipeline, "find_visits",
                        lambda cmd, stop: Track(visits, (), 3, 0))
    return pipeline.run_body(BODY, mjd_stop=61100.0)


def test_pipeline_detects_and_subtracts_control(run):
    (res,) = run.passes
    assert res.detected and res.best.snr > 20
    b1 = next(b for b in res.corrected if b.band == "spx-b1")
    raw = next(b for b in res.bands if b.band == "spx-b1")
    assert b1.flux_mjy == pytest.approx(raw.flux_mjy - 0.001)
    assert res.body_stacks and res.sky is not None
    assert set(run.timings) >= {"ephemeris and frame search", "read stamps", "photometry"}


def test_manifest_validates_and_has_extension(run, tmp_path):
    m = bodymanifest.build(run, tmp_path)
    validate(m, tmp_path)
    json.dumps(m, allow_nan=False)
    assert m["match"] is None and any("not typed" in w for w in m["warnings"])
    assert m["frames"] and all(f["predicted_px"] for f in m["frames"])
    ss = m["solar_system"]
    assert ss["passes"][0]["detected"] and ss["passes"][0]["control"]["n_positions"] == 8
    assert ss["passes"][0]["outcome"] == "detected"
    assert ss["reflectance"][0]["band_depths"] and ss["reflectance"][0]["reading"]
    assert all((tmp_path / f["image"]).is_file() for f in ss["body_frames"]["frames"])
    assert any("Horizons" in c for c in m["credits"])


def test_no_detection_gives_honest_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "find_visits", lambda cmd, stop: Track((), (), 3, 1))
    r = pipeline.run_body(BODY, mjd_stop=61100.0)
    m = bodymanifest.build(r, tmp_path)
    assert m["frames"] == [] and any("not detected" in w for w in m["warnings"])
    assert any("did not answer" in w for w in m["warnings"])
    assert cli.check(m, tmp_path)


def test_cli_rejects_bad_designation(tmp_path):
    assert cli.main(["--body", "Haumea; rm -rf /", "--out", str(tmp_path)]) == 2


def test_pass_type_is_reused():
    assert Pass((frame(61000.0),)).mjd_start == 61000.0


def test_horizons_failure_gives_authored_warning(monkeypatch, tmp_path):
    from pxs.solarsystem.horizons import HorizonsError

    def down(cmd, stop):
        raise HorizonsError("Horizons returned no ephemeris: secret internal text")
    monkeypatch.setattr(pipeline, "find_visits", down)
    r = pipeline.run_body(BODY, mjd_stop=61100.0)
    m = bodymanifest.build(r, tmp_path)
    text = json.dumps(m)
    assert pipeline.HORIZONS_DOWN in m["warnings"] and "secret internal" not in text
    assert not any("not detected" in w for w in m["warnings"])
    assert m["degraded"] and m["solar_system"]["frame_search"] is None


def test_frame_search_is_reported(run, tmp_path):
    fs = bodymanifest.build(run, tmp_path)["solar_system"]["frame_search"]
    assert fs == {"index_days": 0, "sia_cones": 3, "failed_sia_cones": 0, "candidate_frames": 10}


def test_unsearched_tail_is_warned(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "find_visits",
                        lambda cmd, stop: Track((), (), 0, 0, 40, 61318.0))
    m = bodymanifest.build(pipeline.run_body(BODY, mjd_stop=61400.0), tmp_path)
    assert any("not searched" in w and "2026-10-" in w for w in m["warnings"])
