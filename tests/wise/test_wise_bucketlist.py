"""Frames found from the bucket's scan tracks, with no IRSA query (pxs.wise.bucketlist)."""

from __future__ import annotations

import pytest
from astropy.io import fits
from wise_frames import threeband

from pxs.wise import bucketlist
from pxs.wise.bucketlist import ScanPath

# Scan 07101b of the three-band phase (read 15 Nov 2026): ELON0 42.989, ELAT0 31.697 at
# frame 101 and -30.974 at frame 200.
SCAN = ScanPath("07101b", 42.989, 101, 31.697, (-30.974 - 31.697) / 99, 55414.452)


def test_ecliptic_of_the_ecliptic_north_pole_and_the_equinox() -> None:
    _, lat = bucketlist.to_ecliptic(270.0, 66.5607089)
    assert lat == pytest.approx(90.0, abs=1e-5)
    assert bucketlist.to_ecliptic(0.0, 0.0) == pytest.approx((0.0, 0.0), abs=1e-9)


def test_a_point_on_the_track_has_no_cross_track_offset() -> None:
    cross, theta = bucketlist.track_coords(SCAN, 42.989, 10.0)
    assert cross == pytest.approx(0.0, abs=1e-9) and theta == pytest.approx(10.0)
    cross, _ = bucketlist.track_coords(SCAN, 43.989, 0.0)
    assert cross == pytest.approx(1.0)


def test_frame_window_brackets_the_frame_at_the_position() -> None:
    frames = bucketlist.frame_window(SCAN, 42.989, 0.0, 0.6)
    expected = 101 + (0.0 - 31.697) / SCAN.step_deg  # about frame 151
    assert min(frames) < expected < max(frames)
    assert len(frames) <= 9


def test_a_scan_far_from_the_position_has_no_frames() -> None:
    assert bucketlist.frame_window(SCAN, 45.0, 0.0, 0.6) == []
    assert bucketlist.frame_window(SCAN, 42.989 + 180, 0.0, 0.6) == []


def test_path_from_two_headers() -> None:
    a = (101, {"ELON0": "42.989", "ELAT0": "31.697", "MJD_OBS": "55414.45"})
    b = (200, {"ELON0": "42.989", "ELAT0": "-30.974", "MJD_OBS": "55414.46"})
    p = bucketlist.path_from_cards("07101b", a, b)
    assert p.step_deg == pytest.approx(-0.633, abs=1e-3) and p.frame_a == 101


def test_cards_are_parsed_from_raw_header_bytes() -> None:
    raw = b"".join(c.ljust(80).encode() for c in (
        "ELON0   =     42.9892648158384 / Level-0 ADCS frame center ecliptic lon",
        "SCAN    = '07110a  '           / Scan ID"))
    assert bucketlist._cards(raw) == {"ELON0": "42.9892648158384", "SCAN": "07110a"}


def _header() -> fits.Header:
    h = fits.Header()
    for k, v in {"NAXIS": 2, "NAXIS1": 1016, "NAXIS2": 1016, "CTYPE1": "RA---SIN",
                 "CTYPE2": "DEC--SIN", "CRPIX1": 508.5, "CRPIX2": 508.5, "CRVAL1": 84.0,
                 "CRVAL2": -63.0, "CD1_1": -0.000764, "CD1_2": 0.0, "CD2_1": 0.0,
                 "CD2_2": 0.000764, "MJD_OBS": 55414.7, "MOONSEP": 89.0}.items():
        h[k] = v
    return h


def test_frame_from_header_has_the_wcs_footprint_and_no_quality() -> None:
    f = bucketlist.frame_from_header(_header(), "3band", "07110a", 2, "W2")
    assert len(f.corners) == 4 and f.qual_frame is None and f.saa_sep_deg is None
    assert f.mjd == 55414.7 and f.moon_sep_deg == 89.0
    decs = [d for _, d in f.corners]
    assert min(decs) == pytest.approx(-63.39, abs=0.01) and max(decs) == pytest.approx(-62.61,
                                                                                       abs=0.01)


def test_the_tap_rule_keeps_centres_within_reach() -> None:
    assert bucketlist.centre_within(_header(), 84.0, -63.5, 0.6)
    assert not bucketlist.centre_within(_header(), 84.0, -64.0, 0.6)


def _doc() -> dict:
    phases = {"allsky": {"status": "complete", "how": "IRSA SIA2", "frames": 1},
              "3band": {"status": "missing", "how": "timing"},
              "postcryo": {"status": "none", "how": "IRSA SIA2", "frames": 0},
              "neowiser": {"status": "complete", "how": "IRSA SIA2", "frames": 1}}
    rows = [["allsky", "02881b", 50, "W2", 55275.0, None, None, [0.0] * 8],
            ["neowiser", "52699a", 100, "W2", 56919.0, 10, 5.0, [0.0] * 8]]
    return {"version": 1, "ra": 1.0, "dec": 2.0, "radius_deg": 0.03, "phases": phases,
            "frames": rows}


def test_patch_adds_threeband_rows_and_leaves_the_rest() -> None:
    doc = _doc()
    f = bucketlist.frame_from_header(_header(), "3band", "07110a", 2, "W2")
    new = threeband.patch(doc, [f], how="bucket")
    assert new["phases"]["3band"] == {"status": "complete", "how": "bucket", "frames": 1}
    assert [r[0] for r in new["frames"]] == ["allsky", "3band", "neowiser"]
    assert new["phases"]["allsky"] == doc["phases"]["allsky"]
    assert doc["phases"]["3band"]["status"] == "missing" and len(doc["frames"]) == 2


def test_patch_with_no_frames_records_none() -> None:
    assert threeband.patch(_doc(), [])["phases"]["3band"]["status"] == "none"
