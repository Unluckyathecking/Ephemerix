"""GET /api/body/resolve and GET /api/body: validation, SBDB resolution, jobs, cache, errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
from api_helpers import eventually, wait_for

from pxs.api.bodies import (
    BodyParams,
    BodyResolver,
    clean_body_name,
    horizons_command,
)
from pxs.api.jobs import AuthoredFailure
from pxs.api.params import ParamError

SECRET = "Traceback secret-host:5432 password=hunter2"

QUAOAR = {"object": {"fullname": "50000 Quaoar (2002 LM60)", "shortname": "50000 Quaoar",
                   "kind": "an", "des": "50000", "prefix": None, "spkid": "2050000",
                   "orbit_class": {"code": "TNO", "name": "TransNeptunian Object"}}}
ATLAS = {"object": {"fullname": "C/2025 N1 (ATLAS)", "kind": "cu", "des": "2025 N1",
                    "prefix": "C", "spkid": "1004083",
                    "orbit_class": {"code": "HYP", "name": "Hyperbolic Comet"}}}
HALLEY = {"code": "300", "message": "specified query matched more than one object",
          "list": [{"pdes": "2688", "name": "2688 Halley (1982 HG1)"},
                   {"pdes": "1P", "name": "1P/Halley"}, {"pdes": "x;y", "name": "bad"},
                   {"pdes": "99", "name": "<b>"}]}
# SBDB refuses its own display names as queries, so suggestions carry the designation.
SUGGESTED = [{"designation": "2688", "name": "2688 Halley (1982 HG1)"},
             {"designation": "1P", "name": "1P/Halley"}, {"designation": "99", "name": "99"}]
MISSING = {"code": "200", "message": "specified object was not found"}


class FakeSbdb:
    """Answers SBDB URLs from a dict of sstr -> JSON body; records every call."""

    def __init__(self, answers: dict[str, dict] | None = None,
                 fail: Exception | None = None) -> None:
        self.answers, self.fail, self.calls = answers or {}, fail, []

    def __call__(self, url: str, timeout_s: float) -> str:
        self.calls.append(url)
        if self.fail is not None:
            raise self.fail
        sstr = requests.utils.unquote(url.split("sstr=", 1)[1])
        return json.dumps(self.answers.get(sstr, MISSING))


def body_resolver(**answers: dict) -> tuple[BodyResolver, FakeSbdb]:
    fake = FakeSbdb({k.replace("_", " "): v for k, v in answers.items()})
    return BodyResolver(2.0, fetch=fake), fake


class BodyBuild:
    """Writes a minimal body manifest (frames plus a solar_system image), or raises."""

    def __init__(self, fail: BaseException | None = None) -> None:
        self.fail, self.calls = fail, []

    def __call__(self, params: BodyParams, out: Path, report) -> dict:
        self.calls.append(params)
        report("Asking JPL Horizons where the body was", 0.05)
        if self.fail is not None:
            raise self.fail
        (out / "frames").mkdir(parents=True, exist_ok=True)
        (out / "body").mkdir(parents=True, exist_ok=True)
        (out / "frames" / "a.png").write_bytes(b"\x89PNG")
        (out / "body" / "b.png").write_bytes(b"\x89PNG")
        m = {"schema": 1, "target": {"name": params.name, "ra": 1.0, "dec": 2.0},
             "frames": [{"id": "a", "image": "frames/a.png"}], "warnings": [],
             "degraded": False,
             "solar_system": {"designation": params.designation,
                              "body_frames": {"frames": [{"id": "b", "image": "body/b.png"}]}}}
        (out / "manifest.json").write_text(json.dumps(m))
        return m


# ---- validation and resolution (no app) ------------------------------------------------


@pytest.mark.parametrize("raw", ["a" * 41, "Eris;rm", "<b>", "Ceres?x=1", "%20"])
def test_bad_body_names_are_refused(raw: str) -> None:
    with pytest.raises(ParamError):
        clean_body_name(raw)


@pytest.mark.parametrize("raw,want", [(" Eris ", "Eris"), ("433  Eros", "433 Eros"),
                                      ("3I/ATLAS", "3I/ATLAS"), ("C/2025 N1", "C/2025 N1"),
                                      ("2003 EL61", "2003 EL61"), ("d'Arrest", "d'Arrest")])
def test_good_body_names_are_normalised(raw: str, want: str) -> None:
    assert clean_body_name(raw) == want


@pytest.mark.parametrize("obj,want", [
    ({"kind": "an", "des": "136199"}, "136199;"),
    ({"kind": "au", "des": "2024 YR4"}, "DES=2024 YR4;"),
    ({"kind": "cu", "des": "2025 N1", "prefix": "C"}, "DES=C/2025 N1;CAP;NOFRAG"),
    ({"kind": "cn", "des": "1P", "prefix": "P"}, "DES=1P;CAP;NOFRAG"),
    ({"kind": "an", "des": "1; DROP"}, None),
    ({"kind": "au", "des": "2024 YR4'"}, None),
    ({"kind": "zz", "des": "1"}, None),
])
def test_horizons_command_comes_only_from_strict_designations(obj: dict, want) -> None:
    assert horizons_command(obj) == want


def test_curated_bodies_resolve_without_a_network_call() -> None:
    resolver, fake = body_resolver()
    ans = resolver("haumea")
    assert ans["resolved"] and ans["designation"] == "136108" and ans["horizons"] == "136108;"
    assert resolver("Pluto")["horizons"] == "9"
    assert fake.calls == []


def test_sbdb_answers_are_cached_and_ambiguity_gives_suggestions() -> None:
    resolver, fake = body_resolver(Quaoar=QUAOAR, Halley=HALLEY)
    quaoar = resolver("Quaoar")
    assert quaoar == {"resolved": True, "designation": "50000", "name": "50000 Quaoar",
                    "kind": "TransNeptunian Object", "horizons": "50000;"}
    assert resolver.peek("QUAOAR") == quaoar
    resolver("quaoar")
    halley = resolver("Halley")
    assert halley["resolved"] is False
    assert halley["did_you_mean"] == SUGGESTED
    assert "Did you mean" in halley["message"]
    assert resolver("Nowhere")["did_you_mean"] == []
    assert len(fake.calls) == 3


def test_sbdb_down_is_soft_authored_and_not_cached() -> None:
    fake = FakeSbdb(fail=requests.ConnectionError(SECRET))
    resolver = BodyResolver(2.0, fetch=fake)
    ans = resolver("Quaoar")
    assert ans["resolved"] is False and ans.get("unavailable") is True
    assert SECRET not in json.dumps(ans)
    assert resolver.peek("Quaoar") is None


def test_key_follows_the_body_index_and_day_not_the_spelling() -> None:
    a = BodyParams("50000", "Quaoar", "50000;", "TNO", index_tag="i1", day="2026-11-15")
    b = BodyParams("50000", "50000 Quaoar", "50000;", "", index_tag="i1", day="2026-11-15")
    assert a.key == b.key
    assert a.key != BodyParams("50000", "Quaoar", "50000;", "", "i2", "2026-11-15").key
    assert a.key != BodyParams("50000", "Quaoar", "50000;", "", "i1", "2026-11-16").key


# ---- routes ----------------------------------------------------------------------------


def test_resolve_route(make_client) -> None:
    resolver, _ = body_resolver(Quaoar=QUAOAR, Halley=HALLEY)
    client, _ = make_client(body_resolver=resolver)
    ok = client.get("/api/body/resolve", params={"name": "Quaoar"})
    assert ok.status_code == 200
    assert ok.json() == {"resolved": True, "designation": "50000", "name": "50000 Quaoar",
                         "kind": "TransNeptunian Object"}
    amb = client.get("/api/body/resolve", params={"name": "Halley"}).json()
    assert amb["resolved"] is False and amb["did_you_mean"] == SUGGESTED
    assert client.get("/api/body/resolve", params={"name": "a;b"}).status_code == 422
    assert client.get("/api/body/resolve").status_code == 422
    assert client.get("/api/body/resolve", params={"name": "Quaoar", "x": "1"}).status_code == 422


def test_resolve_route_when_sbdb_is_down(make_client) -> None:
    client, _ = make_client(body_resolver=BodyResolver(
        2.0, fetch=FakeSbdb(fail=requests.Timeout(SECRET))))
    r = client.get("/api/body/resolve", params={"name": "Quaoar"})
    assert r.status_code == 503 and "Retry-After" in r.headers
    assert SECRET not in r.text and "JPL Small-Body Database did not answer" in r.text


def test_body_lookups_share_the_resolve_rate_limit(make_client) -> None:
    resolver, _ = body_resolver()
    client, _ = make_client(body_resolver=resolver, resolve_limit=2)
    for name in ("A1", "A2"):
        assert client.get("/api/body/resolve", params={"name": name}).status_code == 200
    assert client.get("/api/body/resolve", params={"name": "A3"}).status_code == 429
    assert client.get("/api/body/resolve", params={"name": "a1"}).status_code == 200  # cached


def test_body_job_then_cached_manifest_with_rewritten_images(make_client) -> None:
    resolver, _ = body_resolver(Quaoar=QUAOAR, **{"50000": QUAOAR})
    build = BodyBuild()
    client, _ = make_client(body_build=build, body_resolver=resolver)
    r = client.get("/api/body", params={"name": "Quaoar"})
    assert r.status_code == 202, r.text
    done = wait_for(client, r.json()["status_url"], {"done", "error"})
    assert done["state"] == "done", done
    assert build.calls[0].horizons == "50000;"
    key = done["manifest_url"].split("/")[3]
    hit = client.get("/api/body", params={"name": "50000"})
    assert hit.status_code == 200 and hit.json()["target"]["name"] == "50000 Quaoar"
    bf = hit.json()["solar_system"]["body_frames"]["frames"][0]["image"]
    assert bf == f"views/{key}/body/b.png"
    assert client.get("/api/" + bf).status_code == 200
    assert len(build.calls) == 1


def test_body_not_found_and_suggestions(make_client) -> None:
    resolver, _ = body_resolver(Halley=HALLEY)
    build = BodyBuild()
    client, _ = make_client(body_build=build, body_resolver=resolver)
    r = client.get("/api/body", params={"name": "Halley"})
    assert r.status_code == 404
    assert r.json()["did_you_mean"] == SUGGESTED
    assert client.get("/api/body", params={"name": "Nowhere"}).status_code == 404
    assert build.calls == []


def test_body_builds_count_against_the_build_rate_limit(make_client) -> None:
    orcus = {"object": {**QUAOAR["object"], "des": "90482", "shortname": "90482 Orcus"}}
    resolver, _ = body_resolver(Quaoar=QUAOAR, Orcus=orcus)
    client, _ = make_client(body_build=BodyBuild(), body_resolver=resolver, rate_limit=1)
    assert client.get("/api/body", params={"name": "Quaoar"}).status_code == 202
    r = client.get("/api/body", params={"name": "Orcus"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_authored_failures_reach_the_client_and_others_do_not(make_client) -> None:
    resolver, _ = body_resolver(Quaoar=QUAOAR, Sedna={"object": {**QUAOAR["object"], "des": "90377"}})
    msg = "No SPHEREx exposure covers this body yet."
    client, _ = make_client(body_build=BodyBuild(AuthoredFailure(msg)), body_resolver=resolver)
    url = client.get("/api/body", params={"name": "Quaoar"}).json()["status_url"]
    assert wait_for(client, url, {"error"})["error"] == msg

    client2, _ = make_client(body_build=BodyBuild(RuntimeError(SECRET)), body_resolver=resolver)
    url = client2.get("/api/body", params={"name": "Sedna"}).json()["status_url"]
    err = wait_for(client2, url, {"error"})
    assert SECRET not in json.dumps(err)


def test_sky_and_body_jobs_share_one_worker_pool(make_client) -> None:
    resolver, _ = body_resolver(Quaoar=QUAOAR)
    client, view_build = make_client(body_build=BodyBuild(), body_resolver=resolver)
    assert client.get("/api/view", params={"ra": "1", "dec": "2"}).status_code == 202
    url = client.get("/api/body", params={"name": "Quaoar"}).json()["status_url"]
    assert wait_for(client, url, {"done"})["state"] == "done"
    view_build.release.set()
    assert eventually(lambda: client.get("/api/health").json()["jobs"]["running"] == 0)


# ---- the body build function -----------------------------------------------------------


class FakePass:
    def __init__(self, detected: bool, marginal: bool = False) -> None:
        self.detected = detected
        self.outcome = "detected" if detected else "marginal" if marginal else "not detected"


def _runner(**fields):
    from pxs.api.bodyrunner import make_body_builder
    from pxs.solarsystem.pipeline import BodyRun

    seen: dict = {}

    def run(body, progress, deadline):
        seen.update(body=body, deadline=deadline)
        progress("Measuring pass 1 of 1", 0.1)
        return BodyRun(body, **fields)

    def render(result, root):
        return {"schema": 1, "frames": [], "warnings": list(result.warnings)}

    return make_body_builder(480.0, run=run, render=render), seen


PARAMS = BodyParams("136199", "Eris", "136199;", "TNO", "none", "2026-11-15")


@pytest.mark.parametrize("fields,message", [
    ({"track": None}, "JPL Horizons did not answer"),
    ({"track": object(), "passes": ()}, "No SPHEREx exposure covers this body yet."),
    ({"track": object(), "passes": (), "stopped_early": True}, "took the whole time allowed"),
    ({"track": object(), "passes": (FakePass(False), FakePass(False))},
     "covered this body in 2 passes but did not detect it"),
    ({"track": object(), "passes": (FakePass(False, marginal=True), FakePass(False))},
     "covered this body in 2 passes. In 1 of them one detector band reached S/N 5"),
])
def test_body_builder_fails_with_authored_sentences(tmp_path, fields, message) -> None:
    build, _ = _runner(**fields)
    with pytest.raises(AuthoredFailure, match=message):
        build(PARAMS, tmp_path, lambda s, f: None)


def test_body_builder_writes_the_manifest_within_the_budget(tmp_path) -> None:
    import time

    build, seen = _runner(track=object(), passes=(FakePass(True),), warnings=("Stopped",))
    stages: list[str] = []
    m = build(PARAMS, tmp_path / "out", lambda s, f: stages.append(s))
    assert json.loads((tmp_path / "out" / "manifest.json").read_text()) == m
    assert seen["body"].name == "Eris" and seen["body"].horizons == "136199;"
    assert 410 < seen["deadline"] - time.monotonic() <= 420  # 480 s less the render margin
    assert stages[-1].startswith("Drawing")


def test_curated_body_keeps_its_blurb() -> None:
    p = BodyParams("136108", "Haumea", "136108;", "dwarf planet", "none", "2026-11-15")
    assert p.body().blurb


def test_every_image_a_body_view_writes_can_be_served() -> None:
    from pxs.api.cache import FILE_RE

    def images(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from [v] if k == "image" and isinstance(v, str) else images(v)
        elif isinstance(node, list):
            for v in node:
                yield from images(v)

    gallery = Path(__file__).resolve().parents[2] / "web" / "gallery"
    for slug in ("haumea", "makemake"):
        found = list(images(json.loads((gallery / slug / "manifest.json").read_text())))
        assert found and all(FILE_RE.fullmatch(p) for p in found), slug


def test_index_tag_follows_the_index_manifest(tmp_path, monkeypatch) -> None:
    from pxs.api.bodyrunner import index_tag

    monkeypatch.delenv("PXS_SPHEREX_INDEX", raising=False)
    assert index_tag() == "none"
    (tmp_path / "manifest.json").write_text('{"a": 1}')
    monkeypatch.setenv("PXS_SPHEREX_INDEX", str(tmp_path))
    first = index_tag()
    (tmp_path / "manifest.json").write_text('{"a": 22}')
    assert first != "none" and index_tag() != first
