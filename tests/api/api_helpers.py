"""Helpers for the live API tests: a controllable builder and a minimal view writer."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from pxs.api.params import ViewParams

Q = {"ra": "150.0123", "dec": "20.0046"}


def write_view(out: Path, params: ViewParams, extra_bytes: int = 0) -> dict:
    """A minimal manifest with one frame, enough for the service (not a full view)."""
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "frames" / "wise-w2-2010a.png").write_bytes(b"\x89PNG" + b"\0" * extra_bytes)
    m = {"schema": 1, "target": {"name": None, "ra": params.ra, "dec": params.dec},
         "frames": [{"id": "wise-w2-2010a", "image": "frames/wise-w2-2010a.png"}],
         "warnings": []}
    (out / "manifest.json").write_text(json.dumps(m))
    return m


class GatedBuild:
    """A build that reports stages and waits for `release` before finishing."""

    def __init__(self, fail: Exception | None = None, extra_bytes: int = 0,
                 gated: bool = True) -> None:
        self.release = threading.Event()
        if not gated:
            self.release.set()
        self.started = threading.Event()
        self.calls = 0
        self.fail, self.extra_bytes = fail, extra_bytes
        self._lock = threading.Lock()

    def __call__(self, params: ViewParams, out: Path, report: Callable[[str, float], None]):
        with self._lock:
            self.calls += 1
        report("Searching WISE frames", 0.1)
        self.started.set()
        while not self.release.wait(0.01):
            report("Searching WISE frames", 0.35)
        report("Writing the view", 0.97)
        if self.fail is not None:
            raise self.fail
        return write_view(out, params, self.extra_bytes)


def eventually(condition: Callable[[], object], timeout: float = 30.0) -> bool:
    """Poll `condition` until it is truthy. The deadline is generous: it only bounds a hang."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def wait_for(client: TestClient, status_url: str, states: set[str],
             timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(status_url).json()
        if body["state"] in states:
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"job stuck in {body}")
        time.sleep(0.01)


def build_now(client: TestClient, query: dict) -> dict:
    """Request a view and wait until it is built; returns the final job status."""
    r = client.get("/api/view", params=query)
    assert r.status_code == 202, r.text
    return wait_for(client, r.json()["status_url"], {"done", "error"})
