import pytest
from conftest import FIXTURES

from pxs.wise.frames import parse_sia, parse_tap
from pxs.wise.phases import PHASES, bucket_key, phase, phase_of_url


@pytest.mark.parametrize("name, expected", [
    ("allsky", "wise/allsky/images/4band_p1bm_frm/7a/05187a/194/05187a194-w1-int-1b.fits"),
    ("3band", "wise/cryo-3band/images/3band_p1bm_frm/5b/08205b/138/08205b138-w1-int-1b.fits"),
    ("postcryo", "wise/postcryo/images/2band_p1bm_frm/5b/10885b/021/10885b021-w1-int-1b.fits"),
    ("neowiser", "wise/neowiser/images/p1bm_frm/9b/54429b/187/54429b187-w1-int-1b.fits"),
])
def test_bucket_key_for_every_phase(name: str, expected: str) -> None:
    scan, num = expected.split("/")[-3], int(expected.split("/")[-2])
    assert bucket_key(name, scan, num, "W1") == expected
    assert bucket_key(name, scan, num, "W2") == expected.replace("-w1-", "-w2-")


def test_sia_access_urls_map_to_the_same_keys() -> None:
    for coll in ("wise_allsky", "wise_2bandcryo", "neowiser"):
        text = (FIXTURES / f"sia_{coll}.csv").read_text()
        frames = parse_sia(text)
        assert frames
        for f in frames:
            p = phase(f.phase)
            url_tail = f.key[len(p.bucket_prefix):]
            assert phase_of_url(p.ibe_prefix + url_tail) == p
            assert f"{f.scan_id}{f.frame_num:03d}-w{f.band[1]}-int-1b.fits" in f.key


def test_tap_rows_give_3band_keys() -> None:
    frames = parse_tap((FIXTURES / "tap_allsky_3band_p1bm_frm.csv").read_text(), "3band")
    keys = {f.key for f in frames}
    # This key answered HEAD 200 from the bucket on 14 Nov 2026.
    assert "wise/cryo-3band/images/3band_p1bm_frm/5b/08205b/138/08205b138-w2-int-1b.fits" in keys


def test_bad_inputs_raise() -> None:
    with pytest.raises(ValueError):
        bucket_key("neowiser", "54429b", 187, "W3")
    with pytest.raises(ValueError):
        bucket_key("nope", "54429b", 187, "W1")
    with pytest.raises(ValueError):
        phase_of_url("https://example.com/x.fits")
    assert len(PHASES) == 4
