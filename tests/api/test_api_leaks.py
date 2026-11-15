"""Exception text never reaches a user: not in job errors, not in manifest warnings."""

from pathlib import Path

from api_helpers import GatedBuild, build_now
from build_fakes import MOVER, FakeSpherex, FakeWise

from pxs import catalogs
from pxs.api.runner import make_builder

SECRET = ("HTTPSConnectionPool(host='irsa.ipac.caltech.edu', port=443): Max retries with url "
          "https://irsa.ipac.caltech.edu/TAP/sync?q=1 while reading /srv/pxs/secret/cache.fits "
          "on internal-db.corp.local")
LEAKS = ("irsa.ipac", "https://", "/srv/pxs", "internal-db", "HTTPSConnectionPool", "Traceback")


class LeakyWise(FakeWise):
    def find_visits(self, ra: float, dec: float):
        raise ConnectionError(SECRET)


class LeakySpherex(FakeSpherex):
    def find_frames(self, ra: float, dec: float):
        raise TimeoutError(SECRET)


def leaky_fetch(url: str, adql: str) -> str:
    raise OSError(SECRET)


def assert_clean(text: str) -> None:
    for leak in LEAKS:
        assert leak not in text, leak


def test_upstream_failures_leave_no_trace_in_response_or_manifest(make_client,
                                                                  tmp_path: Path) -> None:
    builder = make_builder(
        FakeSpherex(MOVER), LeakyWise(MOVER),
        overlays=lambda grid: catalogs.overlays(grid, fetch=leaky_fetch,
                                                cache_dir=tmp_path / "cat"))
    client, _ = make_client(builder)
    q = {"ra": f"{MOVER.ra}", "dec": f"{MOVER.dec}", "pmra": f"{MOVER.pmra_masyr}",
         "pmdec": f"{MOVER.pmdec_masyr}", "epoch": f"{MOVER.epoch}"}
    done = build_now(client, q)
    assert done["state"] == "done", done
    hit = client.get("/api/view", params=q)
    stored = client.get(done["manifest_url"])
    for r in (hit, stored):
        assert r.status_code == 200
        assert_clean(r.text)
    warnings = hit.json()["warnings"]
    assert "WISE images could not be loaded; the archive did not answer." in warnings
    assert "Gaia DR3 sources could not be fetched, so none are marked." in warnings
    assert_clean(str(done))


def test_spherex_search_failure_leaves_no_trace(make_client) -> None:
    builder = make_builder(LeakySpherex(MOVER), FakeWise(MOVER),
                           overlays=lambda grid: ({"gaia": [], "catwise": []}, []))
    client, _ = make_client(builder)
    done = build_now(client, {"ra": f"{MOVER.ra}", "dec": f"{MOVER.dec}"})
    assert done["state"] == "done", done
    text = client.get(done["manifest_url"]).text
    assert_clean(text)
    assert "SPHEREx data could not be loaded; the archive did not answer." in text


def test_failed_build_error_is_a_fixed_sentence(make_client) -> None:
    client, _ = make_client(GatedBuild(RuntimeError(SECRET), gated=False))
    err = build_now(client, {"ra": "10", "dec": "10"})
    assert err["state"] == "error"
    assert_clean(str(err))
