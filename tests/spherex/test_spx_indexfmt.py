"""Header parser and WCS inverse of the frame index, against recorded header bytes."""

from __future__ import annotations

import numpy as np
import pytest

from pxs.spherex.indexfmt import (
    DETECTOR_BAND_M,
    HeaderTruncated,
    UnreadableFrame,
    header_end,
    parse_frame,
    rebuild_key,
    split_key,
)
from pxs.spherex.indexwcs import WcsTable, sky_to_pixel

from .index_helpers import (
    KEY_D1,
    REAL_D1,
    REAL_DEEP,
    REAL_QR3,
    astropy_wcs,
    fake_file,
    image_hdr,
    sky_at,
)


def test_header_end_finds_the_image_header() -> None:
    data = REAL_D1.read_bytes()
    assert header_end(data) == 2880
    assert header_end(data, 2880) == 28800


def test_header_end_truncated() -> None:
    with pytest.raises(HeaderTruncated):
        header_end(REAL_D1.read_bytes()[:20000], 2880)


def test_parse_real_dr1_frame() -> None:
    row = parse_frame(KEY_D1, 65_393_280, REAL_D1.read_bytes())
    assert (row["release"], row["week"], row["detector"]) == ("dr1", "2025W17_4B", 1)
    assert row["obs_id"] == "2025W17_4B_0001_1"
    assert row["mjd"] == pytest.approx(60789.751428261, abs=1e-9)
    assert row["xposure_s"] == pytest.approx(113.5826, abs=1e-3)
    assert (row["naxis1"], row["naxis2"], row["sip_order"]) == (2040, 2040, 3)
    assert len(row["sip_ap"]) == len(row["sip_bp"]) == 10
    assert row["sps_flags"] == "all_sky"
    # the 3.5 deg detector: centre near CRVAL, bounding radius a little over the half-diagonal
    assert row["ra_c"] == pytest.approx(160.617, abs=0.01)
    assert 2.4 < row["radius_deg"] < 2.7
    assert row["inv_err_px"] < 0.1


def test_parse_deep_and_qr3_frames() -> None:
    deep = parse_frame("dr1/level2/2025W17_4B/l2b-v27-2026-196/3/"
                       "level2_2025W17_4B_0021_1D3_spx_l2b-v27-2026-196.fits", 1, REAL_DEEP.read_bytes())
    assert deep["sps_flags"] == "deep_north" and deep["detector"] == 3
    qr3 = parse_frame("qr3/level2/2026W40_2A/l2b-v27-2026-285/1/"
                      "level2_2026W40_2A_0001_3D1_spx_l2b-v27-2026-285.fits", 1, REAL_QR3.read_bytes())
    assert qr3["release"] == "qr3" and qr3["obs_id"] == "2026W40_2A_0001_3"


def test_parse_truncated_bytes_ask_for_more() -> None:
    with pytest.raises(HeaderTruncated):
        parse_frame(KEY_D1, 1, REAL_D1.read_bytes()[:15000])


@pytest.mark.parametrize("bad", [b"", b"<html>no</html>", b"SIMPLE  =" + b" " * 80])
def test_parse_garbage_is_unreadable(bad: bytes) -> None:
    with pytest.raises(UnreadableFrame):
        parse_frame(KEY_D1, 1, bad)


def test_parse_rejects_header_that_disagrees_with_key() -> None:
    with pytest.raises(UnreadableFrame, match="disagrees"):
        parse_frame(KEY_D1.replace("0001_1D1", "0002_1D1"), 1, REAL_D1.read_bytes())


def test_parse_rejects_unsupported_projection() -> None:
    bad = fake_file(10.0, 10.0).replace(b"RA---TAN-SIP", b"RA---SIN-SIP", 1)
    with pytest.raises(UnreadableFrame, match="CTYPE"):
        parse_frame(KEY_D1.replace("0001_1D1", "0100_1D1"), 1, bad)


def test_key_round_trip() -> None:
    parts = split_key(KEY_D1)
    assert rebuild_key(parts["release"], parts["week"], parts["pipeline"],
                       "2025W17_4B_0001_1", int(parts["det"])) == KEY_D1
    retry = "dr1/level2/2025W17_4B/l2b_retry-v27-2026-197/1/level2_2025W17_4B_0035_3D1_spx_l2b_retry-v27-2026-197.fits"
    assert split_key(retry)["pipeline"] == "l2b_retry-v27-2026-197"
    with pytest.raises(UnreadableFrame):
        split_key("dr1/level2/x/y.fits")


def test_detector_bands_match_sia_float_for_float() -> None:
    assert DETECTOR_BAND_M[2][0] * 1e6 == 1.1033000000000002
    assert DETECTOR_BAND_M[6][1] * 1e6 == 5.009600000000001
    assert DETECTOR_BAND_M[4][1] * 1e6 == 3.8473000000000006


@pytest.mark.parametrize("path", [REAL_D1, REAL_DEEP, REAL_QR3])
def test_inverse_wcs_matches_astropy_over_the_detector(path) -> None:
    hdr = image_hdr(path)
    w = astropy_wcs(hdr)
    rng = np.random.default_rng(1)
    px, py = rng.uniform(0.5, 2040.5, 400), rng.uniform(0.5, 2040.5, 400)
    ra, dec = w.all_pix2world(px, py, 1)
    ap = np.array([[hdr.get(f"AP_{p}_{q}", 0.0) for p, q in
                    [(p, q) for p in range(4) for q in range(4 - p)]]])
    bp = np.array([[hdr.get(f"BP_{p}_{q}", 0.0) for p, q in
                    [(p, q) for p in range(4) for q in range(4 - p)]]])
    n = 400
    rep = lambda v: np.full(n, float(v))
    t = WcsTable(rep(hdr["CRVAL1"]), rep(hdr["CRVAL2"]), rep(hdr["CRPIX1"]), rep(hdr["CRPIX2"]),
                 rep(hdr["PC1_1"]), rep(hdr["PC1_2"]), rep(hdr["PC2_1"]), rep(hdr["PC2_2"]),
                 np.repeat(ap, n, 0), np.repeat(bp, n, 0), 3)
    x, y, ok = sky_to_pixel(ra, dec, t)
    assert ok.all()
    assert np.abs(x - px).max() < 0.05 and np.abs(y - py).max() < 0.05


def test_sky_at_helper_is_consistent() -> None:
    ra, dec = sky_at(image_hdr(), 1020.5, 1020.5)
    assert ra == pytest.approx(160.617, abs=0.01) and dec == pytest.approx(30.670, abs=0.01)
