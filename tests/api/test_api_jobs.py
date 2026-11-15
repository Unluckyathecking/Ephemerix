import threading
from pathlib import Path

from api_helpers import GatedBuild, Q, build_now, eventually, wait_for
from build_fakes import MOVER, FakeSpherex, FakeWise, no_overlays

from pxs.api.runner import make_builder
from pxs.build import BuildError


def test_miss_gives_202_then_hit_gives_200(make_client) -> None:
    client, build = make_client()
    r = client.get("/api/view", params=Q)
    assert r.status_code == 202 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status_url"] == f"/api/jobs/{body['job']}"
    build.release.set()
    done = wait_for(client, body["status_url"], {"done", "error"})
    assert done["state"] == "done" and done["progress"] == 1.0 and done["error"] is None
    m = client.get(done["manifest_url"])
    assert m.status_code == 200 and "immutable" in m.headers["cache-control"]
    image = m.json()["frames"][0]["image"]
    assert client.get(done["manifest_url"].rsplit("/", 1)[0] + "/" + image).status_code == 200

    hit = client.get("/api/view", params={**Q, "name": "Some star"})
    assert hit.status_code == 200
    key = done["manifest_url"].split("/")[3]
    frame = hit.json()["frames"][0]["image"]
    assert frame == f"views/{key}/frames/wise-w2-2010a.png"  # relative to /api/view
    assert client.get("/api/" + frame).status_code == 200
    assert hit.json()["target"]["name"] == "Some star"
    assert build.calls == 1


def test_identical_requests_share_one_job(make_client) -> None:
    client, build = make_client()
    a = client.get("/api/view", params=Q).json()
    b = client.get("/api/view", params={**Q, "ra": "150.012300001", "name": "x"}).json()
    assert a["job"] == b["job"]
    build.release.set()
    wait_for(client, a["status_url"], {"done"})
    assert build.calls == 1


def test_job_reports_stages_and_finishes(make_client) -> None:
    client, build = make_client()
    url = client.get("/api/view", params=Q).json()["status_url"]
    assert build.started.wait(5)
    running = wait_for(client, url, {"running"})
    assert running["stage"] == "Searching WISE frames"
    assert 0.0 < running["progress"] < 1.0 and running["queue_position"] is None
    assert running["elapsed_s"] >= 0 and running["manifest_url"] is None
    build.release.set()
    assert wait_for(client, url, {"done", "error"})["stage"] == "Done"


def test_queued_job_has_a_position(make_client) -> None:
    client, build = make_client(max_builds=1)
    first = client.get("/api/view", params=Q).json()
    assert build.started.wait(5)
    second = client.get("/api/view", params={**Q, "dec": "21"}).json()
    status = client.get(second["status_url"]).json()
    assert status["state"] == "queued" and status["queue_position"] == 1
    build.release.set()
    wait_for(client, first["status_url"], {"done"})
    wait_for(client, second["status_url"], {"done"})


def test_failing_build_reports_a_safe_error(make_client) -> None:
    client, _ = make_client(GatedBuild(RuntimeError("boom at /srv/secret https://irsa.example/x"),
                                       gated=False))
    err = build_now(client, Q)
    assert err["state"] == "error"
    assert "problem on the server" in err["error"]
    for leak in ("boom", "/srv", "https", "Traceback"):
        assert leak not in err["error"]
    # a failed view is not cached: the next request starts a new job
    assert client.get("/api/view", params=Q).status_code == 202


def test_no_data_is_reported_plainly(make_client) -> None:
    client, _ = make_client(GatedBuild(BuildError("no images: http://x"), gated=False))
    err = build_now(client, Q)
    assert err["error"].startswith("No WISE or SPHEREx images")


def test_hard_timeout_fires(make_client) -> None:
    client, build = make_client(build_timeout_s=0.3)
    err = build_now(client, Q)
    assert err["state"] == "error" and "longer than 0.3 s" in err["error"]
    # the timed-out build left nothing in the cache, so asking again starts a second build
    assert client.get("/api/view", params=Q).status_code == 202
    assert eventually(lambda: build.calls == 2)


def test_unknown_job_is_404(make_client) -> None:
    client, _ = make_client()
    r = client.get("/api/jobs/doesnotexist")
    assert r.status_code == 404 and "not known" in r.json()["error"]


def test_end_to_end_with_fake_sources_and_progress(make_client, tmp_path: Path) -> None:
    stages: list[str] = []
    lock = threading.Lock()
    inner = make_builder(FakeSpherex(MOVER), FakeWise(MOVER), overlays=no_overlays)

    def build(params, out, report):
        def spy(stage: str, fraction: float) -> None:
            with lock:
                stages.append(stage)
            report(stage, fraction)
        return inner(params, out, spy)

    client, _ = make_client(build)
    q = {"ra": f"{MOVER.ra}", "dec": f"{MOVER.dec}", "pmra": f"{MOVER.pmra_masyr}",
         "pmdec": f"{MOVER.pmdec_masyr}", "epoch": f"{MOVER.epoch}", "fov": "240"}
    done = build_now(client, q)
    assert done["state"] == "done", done
    m = client.get("/api/view", params=q).json()
    assert {f["band"] for f in m["frames"]} == {"W1", "W2", "spx-b1", "spx-b2", "spx-b3", "spx-b4", "spx-b5", "spx-b6"}
    assert all(client.get("/api/" + f["image"]).status_code == 200 for f in m["frames"][:3])
    assert "Searching WISE frames" in stages and "Fitting the spectrum" in stages
    assert any(s.startswith("Reading WISE images (1 of 16)") for s in stages)
    assert any("SPHEREx images (" in s for s in stages)
