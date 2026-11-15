"""Horizons parsing and caching (recorded responses) and strict designation parsing."""

from __future__ import annotations

import json
import os

import pytest

from pxs.solarsystem import horizons
from pxs.solarsystem.bodies import Body, load_bodies, resolve
from pxs.solarsystem.horizons import HorizonsError, ephemeris_at, ephemeris_range, parse


def test_ephemeris_at_parses_recorded_tlist(recorded_horizons):
    pts = ephemeris_at("136108;", [61060.5, 60900.1, 60900.2])
    assert [p.mjd for p in pts] == pytest.approx([61060.5, 60900.1, 60900.2], abs=1e-6)
    p = pts[1]
    assert p.ra == pytest.approx(218.49047452)
    assert p.dec == pytest.approx(14.538888775)
    assert p.vmag == pytest.approx(17.295)
    assert p.r_au == pytest.approx(49.8625, abs=1e-3)
    assert p.delta_au == pytest.approx(50.150, abs=1e-3)
    assert 0 < p.phase_deg < 2 and 60 < p.elong_deg < 120
    assert p.rate_arcsec_h == pytest.approx((0.994391**2 + 1.80486**2) ** 0.5)


def test_requests_observe_from_spherex_and_are_cached(recorded_horizons, monkeypatch):
    ephemeris_range("136108;", 61055.0, 61060.0, "1d")
    assert recorded_horizons[0]["params"]["CENTER"] == "'500@-163182'"
    monkeypatch.setattr(horizons, "_get", lambda p: (_ for _ in ()).throw(AssertionError))
    assert len(ephemeris_range("136108;", 61055.0, 61060.0, "1d")) == 6  # from disk


def test_error_response_raises_and_is_not_cached(monkeypatch):
    monkeypatch.setattr(horizons, "_get", lambda p: {"error": "No matches found."})
    with pytest.raises(HorizonsError):
        ephemeris_at("999999;", [61000.0])
    assert not list(horizons.cache_dir().glob("*.json")) if horizons.cache_dir().exists() else True


def test_parse_rejects_text_without_table():
    with pytest.raises(HorizonsError):
        parse("no table here")


def test_bad_range_rejected():
    with pytest.raises(ValueError):
        ephemeris_range("136108;", 61000.0, 60000.0)


@pytest.mark.parametrize("text,command", [
    ("136108", "136108;"), ("Haumea", "136108;"), ("haumea", "136108;"),
    ("2060", "2060;"), ("C/2025 N1", "DES=C/2025 N1;CAP;NOFRAG"), ("12P", "DES=12P;CAP;NOFRAG"),
])
def test_resolve_accepts(text, command):
    assert resolve(text).horizons == command


@pytest.mark.parametrize("text", [
    "", "0", "12345678", "Haumea; DROP", "136108;", "https://evil.example/", "../etc",
    "C/2025 n1", "A" * 40, "1P;CAP", "ceres'",
])
def test_resolve_rejects(text):
    with pytest.raises(ValueError):
        resolve(text, curated=())


def test_curated_list_is_well_formed():
    bodies = load_bodies()
    assert {"Haumea", "Makemake", "Eris"} <= {b.name for b in bodies}
    for b in bodies:
        assert isinstance(b, Body) and b.horizons and b.slug
    assert len({b.designation for b in bodies}) == len(bodies)


@pytest.mark.network
def test_live_horizons_haumea_from_spherex():
    if os.environ.get("PXS_NETWORK") != "1":
        pytest.skip("network")
    (p,) = ephemeris_at("136108;", [61060.5])
    rec = json.loads((horizons.cache_dir() / next(horizons.cache_dir().glob("*.json")).name)
                     .read_text())
    assert "SPHEREx" in rec["result"]
    assert p.vmag == pytest.approx(17.3, abs=0.2)
