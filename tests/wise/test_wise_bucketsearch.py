"""WISE frames listed from the bucket when IRSA's search answers nothing (pxs.wise.bucketsearch)."""

from dataclasses import replace

import pytest
import requests
from astropy.io import fits

from pxs.wise import bucketlist, bucketsearch, net, search
from pxs.wise.phases import PHASES, bucket_key

REAL_PHASE_FRAMES = bucketsearch.phase_frames  # the autouse fixture replaces the attribute
RA, DEC = 84.0, -63.0


def _header_bytes(ra: float, dec: float, mjd: float = 57000.5) -> bytes:
    h = fits.Header()
    for k, v in {"SIMPLE": True, "BITPIX": -32, "NAXIS": 2, "NAXIS1": 1016, "NAXIS2": 1016,
                 "MJD_OBS": mjd, "CRPIX1": 508.5, "CRPIX2": 508.5, "CRVAL1": ra, "CRVAL2": dec,
                 "CTYPE1": "RA---SIN", "CTYPE2": "DEC--SIN", "CD1_1": -0.000764, "CD1_2": 0.0,
                 "CD2_1": 0.0, "CD2_2": 0.000764, "MOONSEP": 89.0}.items():
        h[k] = v
    return h.tostring().encode("ascii")


class Bucket:
    """Fake bucket: header bytes by key; counts probes and full reads."""

    def __init__(self, centres: dict[tuple[str, int], tuple[float, float]]) -> None:
        self.objects = {bucket_key("neowiser", s, f, b): _header_bytes(*c)
                        for (s, f), c in centres.items() for b in ("W1", "W2")}
        self.probed, self.read = [], []

    def _get(self, key: str, start: int, stop: int) -> bytes:
        if key not in self.objects:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("HTTP 404", response=resp)
        return self.objects[key][start:stop]

    def probe(self, key: str, start: int, stop: int) -> bytes:
        self.probed.append(key)
        return self._get(key, start, stop)

    def fetch(self, key: str, start: int, stop: int) -> bytes:
        self.read.append(key)
        return self._get(key, start, stop)


SCORES = {("52699a", 100): (10, 40.0), ("52699a", 101): (5, None), ("52703a", 100): (0, 12.0)}
CENTRES = {("52699a", 100): (RA, DEC + 0.2), ("52699a", 101): (RA, DEC + 0.83),
           ("52703a", 100): (RA + 0.3, DEC)}


def test_neowise_frames_keeps_the_named_frames_within_reach_with_their_scores() -> None:
    b = Bucket(CENTRES)
    frames = bucketsearch.neowise_frames(RA, DEC, 0.002, scores=SCORES, probe=b.probe,
                                         fetch=b.fetch)
    assert sorted((f.scan_id, f.frame_num, f.band) for f in frames) == [
        ("52699a", 100, "W1"), ("52699a", 100, "W2"), ("52703a", 100, "W1"),
        ("52703a", 100, "W2")]
    assert {f.qual_frame for f in frames if f.scan_id == "52699a"} == {10}
    assert {(f.qual_frame, f.saa_sep_deg) for f in frames if f.scan_id == "52703a"} == {(0, 12.0)}
    assert all(f.phase == "neowiser" and len(f.corners) == 4 and f.mjd == 57000.5 for f in frames)
    # SIA's footprint runs from pixel -0.5 to NAXIS + 0.5: 2 px (5.5") taller than centre to centre.
    plain = bucketlist.frame_from_header(fits.Header.fromstring(_header_bytes(RA, DEC + 0.2)
                                                                .decode()), "neowiser", "52699a", 100, "W1")
    f = next(f for f in frames if f.scan_id == "52699a" and f.band == "W1")
    height = [max(d for _, d in c) - min(d for _, d in c) for c in (f.corners, plain.corners)]
    assert (height[0] - height[1]) * 3600 == pytest.approx(2 * 2.75, abs=0.05)
    # One small W1 probe per named frame; full headers only for the frames within reach.
    assert len(b.probed) == 3 and all(k.endswith("-w1-int-1b.fits") for k in b.probed)
    assert len(b.read) == 4 and not any("52699a101" in k for k in b.read)


def test_a_frame_missing_from_the_bucket_is_skipped_and_w2_alone_is_kept() -> None:
    b = Bucket(CENTRES)
    del b.objects[bucket_key("neowiser", "52699a", 100, "W1")]  # W2 exists, W1 does not
    del b.objects[bucket_key("neowiser", "52703a", 100, "W1")]
    del b.objects[bucket_key("neowiser", "52703a", 100, "W2")]
    frames = bucketsearch.neowise_frames(RA, DEC, 0.002, scores=SCORES, probe=b.probe,
                                         fetch=b.fetch)
    assert [(f.scan_id, f.frame_num, f.band) for f in frames] == [("52699a", 100, "W2")]


def test_a_failed_probe_fails_the_phase_instead_of_dropping_frames(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def down(key: str, start: int, stop: int) -> bytes:
        raise requests.ConnectionError("reset")

    with pytest.raises(requests.ConnectionError):
        bucketsearch.neowise_frames(RA, DEC, 0.002, scores=SCORES, probe=down, fetch=down)
    monkeypatch.setattr(bucketsearch.neoqual, "read_scores", lambda *a, **k: SCORES)
    monkeypatch.setattr(bucketsearch, "_probe", down)
    monkeypatch.setattr(net, "get_range", down)
    assert REAL_PHASE_FRAMES("neowiser", RA, DEC, 0.002) is None


def test_an_unreadable_source_table_is_not_taken_for_no_frames(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*a, **k):
        raise OSError("bucket unreachable")

    monkeypatch.setattr(bucketsearch.neoqual, "read_scores", broken)
    assert REAL_PHASE_FRAMES("neowiser", RA, DEC, 0.002) is None


def test_committed_tracks_cover_every_2010_2011_phase() -> None:
    counts = {name: len(bucketsearch.tracks(name)) for name in bucketsearch.TRACK_PHASES}
    assert counts["3band"] == 1643 and counts["postcryo"] > 3700 and counts["allsky"] > 6200
    p = bucketsearch.tracks("3band")[0]
    assert len(p.scan_id) == 6 and 0.5 < abs(p.step_deg) < 0.7 and 55400 < p.mjd < 55500


def test_2010_phases_are_listed_from_the_tracks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_list(phase_name, paths, ra, dec, radius_deg, fetch, sia_footprint=False):
        assert sia_footprint
        seen[phase_name] = (len(paths), ra, dec, radius_deg, fetch)
        return []

    monkeypatch.setattr(bucketlist, "list_frames", fake_list)
    assert REAL_PHASE_FRAMES("3band", RA, DEC, 0.002) == []
    assert seen["3band"] == (1643, RA, DEC, 0.002, net.get_range)


def _frame(phase: str, qual: int | None, band: str = "W2"):
    f = bucketlist.frame_from_header(fits.Header.fromstring(_header_bytes(RA, DEC).decode()),
                                     phase, "52699a", 100, band)
    return replace(f, qual_frame=qual)


def _irsa_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        raise requests.HTTPError("HTTP 502")

    monkeypatch.setattr(net, "get_text", fake)


def test_irsa_down_every_phase_comes_from_the_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    _irsa_down(monkeypatch)
    monkeypatch.setattr(bucketsearch, "phase_frames",
                        lambda name, *a: [_frame(name, 10 if name == "neowiser" else None)])
    frames = search.search_frames(RA, DEC, 0.002)
    assert {f.phase for f in frames} == {p.name for p in PHASES}
    assert not frames.partial
    assert frames.warnings == (search.NO_QUALITY,)  # the 2010-2011 frames have no score


def test_irsa_down_a_phase_the_bucket_cannot_list_is_named(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _irsa_down(monkeypatch)
    monkeypatch.setattr(bucketsearch, "phase_frames",
                        lambda name, *a: [_frame(name, 10)] if name == "neowiser" else None)
    frames = search.search_frames(RA, DEC, 0.002)
    assert {f.phase for f in frames} == {"neowiser"} and frames.partial
    (w,) = frames.warnings
    assert "2010 (cryogenic), 2010 (three-band), 2010-2011 (post-cryogenic) failed" in w


def test_irsa_and_bucket_down_raises_and_no_frames_is_not_a_failure(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _irsa_down(monkeypatch)
    with pytest.raises(RuntimeError):  # the fixture's bucket lists nothing
        search.search_frames(RA, DEC, 0.002)
    monkeypatch.setattr(bucketsearch, "phase_frames", lambda name, *a: [])
    frames = search.search_frames(RA, DEC, 0.002)
    assert list(frames) == [] and not frames.partial and frames.warnings == ()


def test_only_phases_irsa_did_not_list_are_asked_of_the_bucket(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import FIXTURES

    def fake(url: str, params: dict, *, post: bool = False, **kwargs) -> str:
        if url == search.SIA_URL:
            return (FIXTURES / f"sia_{params['COLLECTION']}.csv").read_text()
        raise requests.HTTPError("HTTP 502")

    asked = []

    def bucket(name, *a):
        asked.append(name)
        return [_frame(name, None)]

    monkeypatch.setattr(net, "get_text", fake)
    monkeypatch.setattr(bucketsearch, "phase_frames", bucket)
    frames = search.search_frames(248.167, 66.755, 0.002)
    assert asked == ["3band"]  # SIA listed the rest; only TAP lists the three-band frames
    assert any(f.phase == "3band" for f in frames) and not frames.partial
    assert frames.warnings == (search.NO_QUALITY,)


def test_a_position_at_an_ecliptic_pole_is_not_listed(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the bucket must not be listed near an ecliptic pole")
    monkeypatch.setattr(bucketsearch.bucketlist, "list_frames", boom)
    monkeypatch.setattr(bucketsearch, "neowise_frames", boom)
    # North ecliptic pole (270, +66.56) and south (90, -66.56).
    for name in ("allsky", bucketsearch.NEOWISE):
        assert REAL_PHASE_FRAMES(name, 270.0, 66.56, 0.1) is None
        assert REAL_PHASE_FRAMES(name, 90.0, -66.56, 0.1) is None
