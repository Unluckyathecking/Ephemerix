import json

import pytest

from pxs.astrometry import propagate
from pxs.spherex import Frame, Target, find_frames, group_passes, query, search_circle
from pxs.spherex.query import parse_votable, s3_key

from .conftest import FIXTURES

KEY = "dr1/level2/2025W18_1B/l2b-v27-2026-196/6/level2_2025W18_1B_0081_2D6_spx_l2b-v27-2026-196.fits"
URL = "https://irsa.ipac.caltech.edu/ibe/data/spherex/" + KEY
WISE0855 = Target("WISE 0855-0714", 133.81890825, -7.247048, 2000.0, -8123.7, 673.2)


def frame(mjd: float, det: int = 1) -> Frame:
    return Frame("spherex_dr1", f"obs{mjd}", det, mjd, f"k/{mjd}", 0.75, 1.1)


def test_s3_key_prefers_cloud_access() -> None:
    cloud = json.dumps({"aws": {"bucket_name": "nasa-irsa-spherex", "key": "x/y.fits"}})
    assert s3_key(URL, cloud) == "x/y.fits"


def test_s3_key_derived_from_access_url() -> None:
    assert s3_key(URL, "") == KEY
    assert s3_key(URL, '{"aws": {}}') == KEY


def test_s3_key_rejects_foreign_url() -> None:
    with pytest.raises(ValueError):
        s3_key("https://example.org/x.fits", "")


def test_parse_recorded_votable() -> None:
    frames = parse_votable((FIXTURES / "sia_eps_ind_b_dr1.xml").read_bytes(), "spherex_dr1")
    assert len(frames) == 10
    assert all(1 <= f.detector <= 6 for f in frames)
    assert all(f.s3_key.startswith("dr1/level2/") and f.s3_key.endswith(".fits") for f in frames)
    assert all(60700 < f.mjd < 61400 and f.em_min_um < f.em_max_um for f in frames)


def test_group_passes_splits_on_gaps_over_20_days() -> None:
    frames = [frame(m) for m in (100.0, 105.0, 125.0, 146.0, 146.5, 300.0)]
    passes = group_passes(list(reversed(frames)))
    assert [len(p.frames) for p in passes] == [3, 2, 1]
    assert (passes[0].mjd_start, passes[0].mjd_end) == (100.0, 125.0)
    assert passes[1].mjd_start == 146.0


def test_group_passes_empty() -> None:
    assert group_passes([]) == []


def test_pass_lists_its_detectors() -> None:
    p = group_passes([frame(1.0, 3), frame(2.0, 1), frame(3.0, 3)])[0]
    assert p.detectors == (1, 3)


def test_search_circle_covers_a_fast_mover() -> None:
    ra, dec, radius = search_circle(WISE0855)
    for year in (2025.0, 2026.0, 2027.0):
        pra, pdec = propagate(WISE0855.ra, WISE0855.dec, 2000.0, -8123.7, 673.2, year)
        assert ((pra - ra) * 0.992) ** 2 + (pdec - dec) ** 2 <= radius**2
    assert radius < 0.01


def test_search_circle_static_target_is_a_point() -> None:
    assert search_circle(Target(None, 10.0, 20.0, 2016.0)) == (10.0, 20.0, 0.0005)


def test_find_frames_merges_collections_and_survives_a_failure(monkeypatch) -> None:
    content = (FIXTURES / "sia_eps_ind_b_dr1.xml").read_bytes()

    def fake(coll: str, ra: float, dec: float, radius: float, **_kw) -> bytes:
        if coll == "spherex_qr3":
            raise RuntimeError("IRSA down")
        return content

    monkeypatch.setattr(query, "_sia_bytes", fake)
    frames = find_frames(331.0, -56.8)
    assert len(frames) == 10
    assert [f.mjd for f in frames] == sorted(f.mjd for f in frames)


def test_find_frames_raises_when_every_collection_fails(monkeypatch) -> None:
    # Code review R5: an archive outage used to read as "no SPHEREx passes at this position".
    def down(coll: str, ra: float, dec: float, radius: float, **_kw) -> bytes:
        raise RuntimeError("IRSA down")

    monkeypatch.setattr(query, "_sia_bytes", down)
    with pytest.raises(RuntimeError, match="every SIA query failed"):
        find_frames(331.0, -56.8)


@pytest.mark.parametrize("ra, dec, radius", [
    (360.0, 0.0, 0.001), (-1.0, 0.0, 0.001), (10.0, 91.0, 0.001), (float("nan"), 0.0, 0.001),
    (10.0, 0.0, 0.0), (10.0, 0.0, float("inf")),
])
def test_find_frames_validates_inputs(ra: float, dec: float, radius: float) -> None:
    with pytest.raises(ValueError):
        find_frames(ra, dec, radius)


def test_target_validation() -> None:
    with pytest.raises(ValueError):
        Target("x", 10.0, 95.0, 2000.0)
    with pytest.raises(ValueError):
        Target("x", 10.0, 0.0, 2000.0, pmra_masyr=1.0)
    with pytest.raises(ValueError):
        Target("x", 10.0, 0.0, float("nan"))


@pytest.mark.network
def test_live_sia_finds_eps_ind_b() -> None:
    frames = find_frames(331.08, -56.79)
    assert len(frames) > 100
    assert {f.collection for f in frames} <= {"spherex_dr1", "spherex_qr3"}
