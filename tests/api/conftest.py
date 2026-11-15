"""Fixtures for the live API tests: settings in a temp dir and a client factory."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "assembly"))

from api_helpers import GatedBuild

from pxs.api import create_app
from pxs.api.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", max_builds=2, queue_cap=2,
                    build_timeout_s=10.0, rate_limit=6, rate_window_s=600.0,
                    allowed_origins=("https://site.example",))


@pytest.fixture
def make_client(settings: Settings) -> Iterator:
    """make(build=None, resolver=None, **settings_changes) -> (client, build)."""
    made: list[tuple[TestClient, object]] = []

    def make(build=None, resolver=None, body_build=None, body_resolver=None, **changes):
        build = GatedBuild() if build is None else build
        app = create_app(replace(settings, **changes), build_fn=build, resolver=resolver,
                         body_build_fn=body_build, body_resolver=body_resolver)
        client = TestClient(app)
        made.append((client, build))
        return client, build

    yield make
    for client, build in made:
        if isinstance(build, GatedBuild):
            build.release.set()
        client.app.state.jobs.close()
        client.close()


@pytest.fixture(autouse=True)
def _closed_breakers():
    """Every test starts and ends with every service's circuit breaker closed (they are
    process-wide, so a test that simulates a dead archive must not affect the next one)."""
    from pxs import concurrency

    concurrency.reset_breakers()
    yield
    concurrency.reset_breakers()
