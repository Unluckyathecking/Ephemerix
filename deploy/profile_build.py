"""Time one view build stage by stage: wall time per data-module call, HTTP per host, CPU.

    PYTHONPATH=src python deploy/profile_build.py --target 2mass-0415-0935 --out /tmp/prof

Runs `pxs.build.build_view` with the real data modules wrapped by timers and every
`requests` call counted. Prints a JSON report (also written to <out>/profile.json). Used
locally and inside an ephemeral Modal container (deploy/modal_profile.py); not part of
the service.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

log = logging.getLogger("pxs.profile")


class Recorder:
    """Thread-safe log of (name, start, end) spans and HTTP calls per host."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.spans: list[tuple[str, float, float]] = []
        self.http: dict[str, list[float]] = defaultdict(list)
        self.http_bytes: dict[str, int] = defaultdict(int)
        self.http_errors: dict[str, int] = defaultdict(int)
        self.stages: list[tuple[float, str, float]] = []
        self._lock = threading.Lock()

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def span(self, name: str, start: float) -> None:
        with self._lock:
            self.spans.append((name, start, self.now()))

    def stage(self, text: str, fraction: float) -> None:
        with self._lock:
            self.stages.append((round(self.now(), 2), text, round(fraction, 3)))

    def report(self) -> dict:
        by: dict[str, list[float]] = defaultdict(list)
        for name, a, b in self.spans:
            by[name].append(b - a)
        first = {n: min(a for m, a, _ in self.spans if m == n) for n in by}
        last = {n: max(b for m, _, b in self.spans if m == n) for n in by}
        calls = {n: {"calls": len(v), "sum_s": round(sum(v), 2), "max_s": round(max(v), 2),
                     "first_start_s": round(first[n], 2), "last_end_s": round(last[n], 2)}
                 for n, v in sorted(by.items())}
        hosts = {h: {"requests": len(v), "sum_s": round(sum(v), 2),
                     "max_s": round(max(v), 2), "mb": round(self.http_bytes[h] / 1e6, 2),
                     "errors": self.http_errors[h]} for h, v in sorted(self.http.items())}
        return {"calls": calls, "http": hosts, "stages": self.stages}


REC = Recorder()


def _patch_requests() -> None:
    orig = requests.Session.request

    def request(self, method, url, *args, **kwargs):
        host = urlsplit(url).hostname or "?"
        t = time.perf_counter()
        try:
            resp = orig(self, method, url, *args, **kwargs)
        except Exception:
            with REC._lock:
                REC.http_errors[host] += 1
                REC.http[host].append(time.perf_counter() - t)
            raise
        with REC._lock:
            REC.http[host].append(time.perf_counter() - t)
            REC.http_bytes[host] += len(resp.content or b"")
        return resp

    requests.Session.request = request  # type: ignore[method-assign]


class Timed:
    """Proxy timing every call of a data module's public functions."""

    def __init__(self, inner: Any, prefix: str) -> None:
        self._inner, self._prefix = inner, prefix

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or name.startswith("_"):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            start = REC.now()
            try:
                return attr(*args, **kwargs)
            finally:
                REC.span(f"{self._prefix}.{name}", start)

        return call


def _start_yappi():
    """CPU profile of every thread when PXS_PROFILE_YAPPI=1 (needs yappi installed)."""
    if os.environ.get("PXS_PROFILE_YAPPI") != "1":
        return None
    import yappi

    yappi.set_clock_type("cpu")
    yappi.start(builtins=True)
    return yappi


def _yappi_top(yappi, n: int = 45) -> list[list]:
    yappi.stop()
    stats = yappi.get_func_stats()
    stats.sort("ttot", "desc")
    top = [[round(f.ttot, 2), round(f.tsub, 2), f.ncall, f"{f.module}:{f.lineno} {f.name}"]
           for f in list(stats)[:n]]
    stats.sort("tsub", "desc")
    top += [["self"]] + [[round(f.ttot, 2), round(f.tsub, 2), f.ncall,
                          f"{f.module}:{f.lineno} {f.name}"] for f in list(stats)[:n]]
    return top


class _RssPeak:
    """Peak summed resident memory of every process on the machine (Linux /proc), sampled
    twice a second: in a container that is this build plus its worker processes."""

    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def _total_kb() -> int:
        total = 0
        for status in Path("/proc").glob("[0-9]*/status"):
            try:
                line = next(x for x in status.read_text().splitlines() if x.startswith("VmRSS"))
                total += int(line.split()[1])
            except (OSError, StopIteration, ValueError):
                continue
        return total

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            self.peak = max(self.peak, self._total_kb())

    def stop(self) -> int | None:
        self._stop.set()
        return round(self.peak / 1024) if self.peak else None


def run(slug: str, out: Path, fov: float = 240.0, size: int = 240) -> dict:
    from pxs import build, catalogs
    from pxs.api import progress
    from pxs.api.progress import SpherexProgress, WiseProgress

    Combined = getattr(progress, "Combined", None)

    _patch_requests()
    target = next(t for t in build.load_targets(build.REPO / "data" / "targets.json")
                  if t.slug == slug)
    spherex, wise = build.real_source("pxs.spherex"), build.real_source("pxs.wise")

    def overlays(grid):
        start = REC.now()
        try:
            return catalogs.overlays(grid)
        finally:
            REC.span("catalogs.overlays", start)

    out.mkdir(parents=True, exist_ok=True)
    peak = _RssPeak()
    yappi = _start_yappi()
    cpu0, wall0 = time.process_time(), time.perf_counter()
    REC.t0 = wall0
    if Combined is not None:  # wired as pxs.api.runner does
        both = Combined(REC.stage)
        spx = SpherexProgress(Timed(spherex, "spherex"), both.part("spherex"), (0.0, 1.0))
        wse = WiseProgress(Timed(wise, "wise"), both.part("wise"), (0.0, 1.0))
    else:  # an older tree, profiled for the "before" numbers
        spx = SpherexProgress(Timed(spherex, "spherex"), REC.stage)
        wse = WiseProgress(Timed(wise, "wise"), REC.stage)
    manifest = build.build_view(target, build.GridParams(fov, size), spx, wse, out,
                                overlays=overlays, progress=REC.stage)
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    rep = REC.report()
    if yappi is not None:
        rep["cpu_top"] = _yappi_top(yappi)
    rep["manifest"] = manifest
    rep.update(target=slug, wall_s=round(wall, 1), cpu_s=round(cpu, 1),
               rss_peak_mb=peak.stop(),
               cpus=os.cpu_count(), frames=len(manifest["frames"]),
               degraded=manifest.get("degraded"), warnings=manifest["warnings"])
    (out / "profile.json").write_text(json.dumps(rep, indent=1) + "\n")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(run(args.target, args.out), indent=1))


if __name__ == "__main__":
    main()
