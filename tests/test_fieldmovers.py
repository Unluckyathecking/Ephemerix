"""`fieldmovers`: what else moved in the field, on synthetic WISE visits."""

import json

import numpy as np
import pytest

from pxs import fieldmovers, manifest
from pxs.astrometry import decimal_year
from pxs.fieldmovers import block, detect, label, link
from pxs.grid import Grid, Stack
from pxs.target import Target

SIGMA = {"W2": 7.3 / 2.3548, "W1": 6.7 / 2.3548}
N = 160
GRID = Grid(center_ra=62.76, center_dec=47.24, fov_arcsec=float(N), size_px=N)
T = Target(name="t", ra=GRID.center_ra, dec=GRID.center_dec, epoch=2017.2)
MJDS = 51544.5 + (np.linspace(2010.2, 2024.2, 22) - 2000.0) * 365.25
STARS = ((30.0, 30.0, 40.0), (120.0, 40.0, 25.0), (40.0, 125.0, 60.0), (125.0, 120.0, 15.0),
         (80.0, 25.0, 30.0), (25.0, 80.0, 20.0))
START = (100.0, 70.0)  # the mover's place at 2017.2, px
PM = (600.0, -300.0)  # mas/yr


def _mover_xy(year: float, pm=PM) -> tuple[float, float]:
    return START[0] - pm[0] / 1000.0 * (year - 2017.2), START[1] - pm[1] / 1000.0 * (year - 2017.2)


def _stacks(pm=PM, amp: float = 12.0, band: str = "W2", seed: int = 0, n: int = 22):
    """`n` visits of six static stars and one source moving at `pm` (None: no such source)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:N, 0:N] + 0.5
    out = []
    for mjd in MJDS[:n]:
        img = 100.0 + rng.normal(0.0, 1.0, (N, N))
        src = [*STARS, *(((*_mover_xy(float(decimal_year(mjd)), pm), amp),) if pm else ())]
        for x, y, a in src:
            img = img + a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA[band] ** 2))
        out.append((band, Stack(image=img.astype(np.float32), mission="WISE", band=band,
                                wavelength_um=(4.0, 5.2), mjd=float(mjd), date_span_days=1.0,
                                n_exposures=12, native_pixscale_arcsec=2.75)))
    return out


def _ids(stacks) -> list[str]:
    return [f"wise-{b.lower()}-{k}" for k, (b, _) in enumerate(stacks)]


@pytest.fixture(autouse=True)
def _list_candidates(monkeypatch) -> None:
    """These tests look at the candidates; the default (withheld) has its own test."""
    monkeypatch.setattr(block, "SHIP_CANDIDATES", True)


def _search(stacks, target=T, gaia=(), catwise=()):
    return fieldmovers.search(target, GRID, stacks, _ids(stacks), list(gaia), list(catwise))


def _cat(pm, year: float, key: str = "s") -> dict:
    """A catalogue row at the mover's place at `year` with motion `pm`."""
    x, y = _mover_xy(year)
    ra = GRID.center_ra - (x - N / 2) / 3600.0 / np.cos(np.radians(GRID.center_dec))
    return {"id": key, "ra": float(ra), "dec": GRID.center_dec - (y - N / 2) / 3600.0,
            "epoch": year, "pmra_masyr": pm[0], "pmdec_masyr": pm[1]}


def test_finds_the_mover_and_measures_its_motion() -> None:
    stacks = _stacks()
    before = [st.image.copy() for _, st in stacks]
    b = _search(stacks)
    manifest._check_field_movers(b, N, bad := [])
    assert bad == [] and json.dumps(b, allow_nan=False)
    assert b["status"] == "searched" and b["n_tracked"] == {"W2": 7}
    assert b["n_candidates"] == 1 and b["n_known"] == 0 and not b["candidates_withheld"]
    (m,) = b["movers"]
    assert m["label"] == "candidate" and m["bands"] == ["W2"] and m["n_epochs"] == 22
    assert m["epochs"] == _ids(stacks)
    assert abs(m["pmra_masyr"] - PM[0]) < 3 * m["err_masyr"] < 60
    assert abs(m["pmdec_masyr"] - PM[1]) < 3 * m["err_masyr"]
    assert np.hypot(m["px"][0] - _mover_xy(m["epoch"])[0], m["px"][1] - _mover_xy(m["epoch"])[1]) < 0.5
    assert m["shift_arcsec"] == pytest.approx(0.6708 * 14.0, rel=0.05) and m["significance"] > 20
    assert "1 unexplained candidate" in b["sentence"] and "2010 and 2024" in b["sentence"]
    assert b["null_trials"] == block.NULL_TRIALS and b["null_count"] < 1
    assert all(np.array_equal(a, st.image) for a, (_, st) in zip(before, stacks))  # untouched


def test_a_static_field_has_no_movers_and_says_so() -> None:
    b = _search(_stacks(pm=None))
    assert b["movers"] == [] and b["n_tracked"] == {"W2": 6} and b["null_count"] == 0
    assert b["sentence"].endswith("We found nothing unexplained.")


def test_a_slow_or_faint_source_is_not_called_a_mover() -> None:
    assert _search(_stacks(pm=(40.0, -20.0)))["movers"] == []  # 0.6" in 14 years: under 1"
    assert _search(_stacks(amp=0.5))["movers"] == []  # under S/N 5 in single visits


def test_gaia_explains_a_mover_only_when_the_motion_matches() -> None:
    known = _search(_stacks(), gaia=[_cat(PM, 2016.0, "g1")])
    assert [m["label"] for m in known["movers"]] == ["gaia"]
    assert known["movers"][0]["gaia_id"] == "g1" and known["n_known"] == 1
    assert "1 star already known to move and nothing unexplained" in known["sentence"]
    static = _search(_stacks(), gaia=[_cat((2.0, -1.0), 2017.2, "g2")])
    assert static["movers"] == [] and static["n_contradicted"] == 1 and static["n_candidates"] == 0
    nopm = _search(_stacks(), gaia=[{**_cat(PM, 2016.0), "pmra_masyr": None, "pmdec_masyr": None}])
    assert [m["label"] for m in nopm["movers"]] == ["candidate"]


def test_catwise_and_the_target_are_named() -> None:
    cw = _search(_stacks(), catwise=[_cat((560.0, -330.0), 2015.4, "J1")])
    assert [(m["label"], m["catwise_id"]) for m in cw["movers"]] == [("catwise", "J1")]
    assert "1 object already known to move" in cw["sentence"]
    wrong = _search(_stacks(), catwise=[_cat((0.0, 0.0), 2015.4, "J2")])
    assert [(m["label"], m["catwise_id"]) for m in wrong["movers"]] == [("candidate", "J2")]
    row = _cat(PM, 2017.2)
    me = Target(name="m", ra=row["ra"], dec=row["dec"], epoch=2017.2, pmra_masyr=PM[0],
                pmdec_masyr=PM[1])
    for target in (me, Target(name="m", ra=row["ra"], dec=row["dec"], epoch=2017.2)):
        b = _search(_stacks(), target=target)
        assert [m["label"] for m in b["movers"]] == ["target"] and b["n_candidates"] == 0
        assert "picked up the target itself" in b["sentence"]


def test_the_two_bands_must_agree() -> None:
    both = _stacks() + _stacks(band="W1", seed=1)
    b = _search(both)
    assert len(b["movers"]) == 1 and b["movers"][0]["bands"] == ["W2", "W1"]
    assert len(b["movers"][0]["epochs"]) == 44 and b["n_band_conflicts"] == 0
    still = _stacks() + _stacks(pm=(0.0, 0.0), band="W1", seed=1)  # W1 sees it standing still
    b = _search(still)
    assert b["movers"] == [] and b["n_band_conflicts"] == 1


def test_not_searched_says_why() -> None:
    stacks = _stacks()
    for gaia, catwise in ((None, []), ([], None)):
        b = fieldmovers.search(T, GRID, stacks, _ids(stacks), gaia, catwise)
        assert b["status"] == "not_searched" and b["reason"] == fieldmovers.NO_CATALOGUES
        assert b["sentence"].startswith("We did not search this patch") and b["movers"] == []
    few = _stacks(n=5)
    assert _search(few)["reason"] == fieldmovers.NO_VISITS
    assert _search([])["reason"] == fieldmovers.NO_VISITS
    manifest._check_field_movers(_search(few), N, bad := [])
    assert bad == []


def test_a_failure_inside_the_search_is_reported_not_raised(monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(block, "assemble", boom)
    assert _search(_stacks())["reason"] == fieldmovers.FAILED


def test_candidates_are_withheld_unless_the_build_ships_them(monkeypatch) -> None:
    monkeypatch.undo()
    assert block.SHIP_CANDIDATES is False  # the shipped default: known movers only
    b = _search(_stacks())
    assert b["movers"] == [] and b["n_candidates"] == 1 and b["candidates_withheld"]
    assert b["sentence"].endswith(
        "We found no catalogued star that moved enough to measure. 1 possible mover that no "
        "catalogue explains is not listed, because this search cannot yet tell such movers "
        "from false alarms.")
    known = _search(_stacks(), gaia=[_cat(PM, 2016.0, "g1")])  # a known mover is still listed
    assert [m["label"] for m in known["movers"]] == ["gaia"] and known["candidates_withheld"]
    assert known["sentence"].endswith("1 star already known to move and nothing unexplained.")
    stacks = _stacks()
    bands = [block.band_of(stacks, _ids(stacks), GRID, "W2")]
    assert len(block.assemble(bands, T, GRID, [], [], ship_candidates=True)["movers"]) == 1


def test_shuffled_dates_keep_the_sources_and_break_the_track() -> None:
    stacks = _stacks()
    ep = detect.epochs(stacks, _ids(stacks), GRID, "W2")
    fake = detect.scrambled(ep, np.random.default_rng(3))
    assert np.array_equal(fake.years, ep.years) and sorted(fake.ids) == sorted(ep.ids)
    assert fake.ids != ep.ids and ep.ids == tuple(_ids(stacks))  # input untouched
    band = block.Band(fake, tuple(link.tracks(fake)))
    assert block.movers([band])[0] == [] and len(band.tracks) >= 6


def test_fit_recovers_a_straight_line_exactly() -> None:
    t = np.linspace(2010.0, 2024.0, 9)
    xy = np.column_stack([50.0 + 0.4 * (t - 2017.0), 60.0 - 0.2 * (t - 2017.0)])
    t0, x0, y0, vx, vy, _, ev, chi2 = link.fit(t, xy, np.full(9, 0.1))
    assert (t0, x0, y0) == pytest.approx((2017.0, 50.0, 60.0))
    assert (vx, vy) == pytest.approx((0.4, -0.2)) and chi2 == pytest.approx(0.0, abs=1e-9)
    assert ev == pytest.approx(0.1 / np.sqrt(((t - 2017.0) ** 2).sum()))


def test_agrees_needs_size_and_direction() -> None:
    assert label.agrees((600.0, -300.0), 10.0, (560.0, -330.0))
    assert not label.agrees((600.0, -300.0), 10.0, (-600.0, 300.0))
    assert not label.agrees((100.0, 0.0), 10.0, (5.0, 0.0))  # a static star explains nothing
    assert label.agrees((100.0, 0.0), 30.0, (40.0, 0.0))  # within 3 sigma


def _track(x0: float, snr: float, vx: float = 0.0) -> link.Track:
    return link.Track(2017.0, x0, 50.0, vx, 0.0, 0.01, 0.001, 1.0, snr, tuple(range(22)),
                      (0,) * 22)


def test_a_track_in_the_wings_of_a_much_brighter_source_is_refused() -> None:
    stacks = _stacks(pm=None)
    ep = detect.epochs(stacks, _ids(stacks), GRID, "W2")
    faint, bright, far = _track(60.0, 6.0, 0.5), _track(70.0, 300.0), _track(100.0, 300.0)
    assert block._in_wings(faint, block.Band(ep, (faint, bright)))
    assert not block._in_wings(faint, block.Band(ep, (faint, far)))
    assert not block._in_wings(faint, block.Band(ep, (faint, _track(70.0, 100.0))))
    assert block.moved(faint, block.Band(ep, (faint, far)))
    assert not block.moved(faint, block.Band(ep, (faint, bright)))


def test_coverage_counts_only_visits_inside_the_image() -> None:
    stacks = _stacks(pm=None)
    ep = detect.epochs(stacks, _ids(stacks), GRID, "W2")
    assert block.coverage(_track(60.0, 6.0), ep) == 1.0
    half = link.Track(2017.0, 60.0, 50.0, 0.0, 0.0, 0.01, 0.001, 1.0, 6.0, tuple(range(11)),
                      (0,) * 11)
    assert block.coverage(half, ep) == 0.5
    leaving = link.Track(2017.0, 150.0, 50.0, 3.0, 0.0, 0.01, 0.001, 1.0, 6.0, tuple(range(11)),
                         (0,) * 11)  # past the edge after 2018: seen in every visit it could be
    assert block.coverage(leaving, ep) > 0.7


def test_validation_rejects_a_broken_block() -> None:
    good = _search(_stacks())
    for broken in ({**good, "status": "maybe"}, {**good, "sentence": ""},
                   {**good, "movers": [{**good["movers"][0], "label": "discovery"}]},
                   {**good, "movers": [{**good["movers"][0], "px": [-1.0, 5.0]}]},
                   {"status": "not_searched", "sentence": "s", "movers": [], "reason": None}):
        manifest._check_field_movers(broken, N, bad := [])
        assert bad
    manifest._check_field_movers(None, N, bad := [])  # older manifests have no block
    assert bad == []
