"""The live lookup service (pxs.api) on Modal.

Deploy with `modal deploy deploy/modal_app.py` (see deploy/README.md). Importing this file
only defines the image and function; it makes no account call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent

# ---- Settings -------------------------------------------------------------------------

APP_NAME = "pxs-lookup"
VOLUME_NAME = "pxs-cache"

# The site calls the service on its own origin through web/middleware.js, so browsers never
# call this host and CORS is not needed: no origin is allowed. For local development with
# ?api= (web/js/config.js), run the service yourself with PXS_ALLOWED_ORIGINS set.
PXS_ALLOWED_ORIGINS = ""

# Only requests from the site's proxy are served: they carry PXS_PROXY_SECRET (from the
# Modal secret "pxs-proxy", never written here) and the visitor's address in
# x-pxs-client-ip, which is the rate-limit key. Anything else gets 403 (health answers a
# bare status). With the secret set, X-Forwarded-For is never read, so PXS_TRUST_PROXY
# stays "0". See deploy/README.md ("Same-origin proxy").
PXS_REQUIRE_PROXY = "1"
PXS_TRUST_PROXY = "0"

# Service defaults, repeated so a change is a visible edit here.
PXS_CACHE_MAX_MB = "2048"
PXS_MAX_BUILDS = "2"
PXS_QUEUE_CAP = "8"
PXS_BUILD_TIMEOUT_S = "480"  # a cold view measured over 240 s on 2 cores; revisit when builds are faster
PXS_RATE_LIMIT = "6"
PXS_RATE_WINDOW_S = "600"
PXS_RESOLVE_LIMIT = "20"  # name lookups per client per PXS_RESOLVE_WINDOW_S (default 600)
PXS_DEGRADED_TTL_S = "600"  # a view built from partial data is kept this long, not cached
PXS_MAX_ABANDONED = "4"  # timed-out builds still stuck in a network call; at this: unhealthy
# Opt-in last resort ("1" to enable): exit the process when stuck at that cap for 30 s so
# Modal starts a fresh container. Loses in-memory jobs; see deploy/README.md before enabling.
PXS_EXIT_WHEN_STUCK = "0"
PXS_UPSTREAM_CACHE_MAX_MB = "1024"
# Worker processes for the CPU-heavy steps (pxs.procs): one per core. Builds are Python-bound,
# so on threads alone 8 cores did the work of about 2. "0" turns it off.
PXS_PROCESSES = "8"

# One storage budget. Only finished views (capped at PXS_CACHE_MAX_MB, evicted oldest-first)
# live on the persistent volume. The upstream data caches (WISE, SPHEREx, catalogues) are
# plain downloads that are safe to lose, so they sit on the container's own disk, are
# dropped at scale-to-zero, and are also swept to PXS_UPSTREAM_CACHE_MAX_MB after every
# build, so a long-lived container cannot fill its disk either.
APP_DIR = "/app"
CACHE_ROOT = f"{APP_DIR}/cache"
VIEW_CACHE_MOUNT = f"{CACHE_ROOT}/api"  # the volume
UPSTREAM_CACHE_DIRS = [f"{CACHE_ROOT}/wise", f"{CACHE_ROOT}/spherex", f"{CACHE_ROOT}/catalogs",
                       f"{CACHE_ROOT}/horizons"]  # JPL Horizons answers for body views

# ---- Image ----------------------------------------------------------------------------


def _base_image() -> modal.Image:
    """Python plus the runtime dependencies exactly as uv.lock pins them.

    The pins are exported at deploy time (needs `uv` on the PATH, nothing else). In the
    container this file is imported again, where there is no repository to read; the image
    already exists then, so the install step is skipped.
    """
    base = modal.Image.from_registry("python:3.12-slim")
    if not modal.is_local():
        return base
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lock_requirements import export_requirements

    pins = export_requirements(REPO, REPO / "deploy" / ".build" / "requirements.txt")
    return base.uv_pip_install(requirements=[str(pins)])


image = (
    _base_image()
    .env({"PYTHONPATH": f"{APP_DIR}/src", "PYTHONUNBUFFERED": "1"})
    # pxs finds data/ and the default cache relative to the source tree, so keep the
    # repository layout: /app/src/pxs and /app/data. Only these two directories go in.
    .add_local_dir(REPO / "src", f"{APP_DIR}/src", copy=True,
                   ignore=["**/__pycache__", "**/*.pyc"])
    .add_local_dir(REPO / "data", f"{APP_DIR}/data", copy=True)
)

cache_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
# Our own index of SPHEREx frames, built by
# tools/spherex_index and mounted read-only, so SPHEREx lookups do not need IRSA's search.
INDEX_VOLUME_NAME = "pxs-index"
INDEX_MOUNT = "/index/spherex"
index_volume = modal.Volume.from_name(INDEX_VOLUME_NAME)

app = modal.App(APP_NAME, image=image)

# ---- Service --------------------------------------------------------------------------


@app.function(
    cpu=8.0,  # the SPHEREx PSF fits are CPU-bound; 2 cores took over 240 s for a cold view
    memory=8192,  # MiB
    # Per request, and far above the service's own 480 s build limit.
    timeout=900,
    # One container: jobs, the queue and the rate limiter live in this process's memory.
    max_containers=1,
    # Scale to zero (min_containers defaults to 0); stay warm 10 minutes for follow-up clicks.
    scaledown_window=600,
    # SPHEREx data is in AWS us-east-1. Pinning a compute region carries a price multiplier
    # on Modal's usage rates.
    region="us-east",
    volumes={VIEW_CACHE_MOUNT: cache_volume, INDEX_MOUNT: index_volume.read_only()},
    # PXS_PROXY_SECRET, shared with the Vercel proxy. Create once: deploy/README.md.
    secrets=[modal.Secret.from_name("pxs-proxy")],
    env={
        "PXS_SPHEREX_INDEX": INDEX_MOUNT,
        # Also ask IRSA for frames newer than the index, so new weekly data is not missed.
        "PXS_SPHEREX_INDEX_SIA_TAIL": "1",
        "PXS_ALLOWED_ORIGINS": PXS_ALLOWED_ORIGINS,
        "PXS_TRUST_PROXY": PXS_TRUST_PROXY,
        "PXS_REQUIRE_PROXY": PXS_REQUIRE_PROXY,
        "PXS_CACHE_MAX_MB": PXS_CACHE_MAX_MB,
        "PXS_MAX_BUILDS": PXS_MAX_BUILDS,
        "PXS_QUEUE_CAP": PXS_QUEUE_CAP,
        "PXS_BUILD_TIMEOUT_S": PXS_BUILD_TIMEOUT_S,
        "PXS_RATE_LIMIT": PXS_RATE_LIMIT,
        "PXS_RATE_WINDOW_S": PXS_RATE_WINDOW_S,
        "PXS_RESOLVE_LIMIT": PXS_RESOLVE_LIMIT,
        "PXS_DEGRADED_TTL_S": PXS_DEGRADED_TTL_S,
        "PXS_MAX_ABANDONED": PXS_MAX_ABANDONED,
        "PXS_EXIT_WHEN_STUCK": PXS_EXIT_WHEN_STUCK,
        "PXS_UPSTREAM_CACHE_MAX_MB": PXS_UPSTREAM_CACHE_MAX_MB,
        "PXS_PROCESSES": PXS_PROCESSES,
        # Cache locations. Views: the volume. WISE and SPHEREx: container disk (SPHEREx
        # appends "spherex" to PXS_CACHE). The catalogue cache needs no variable: it
        # defaults to <repo>/cache/catalogs = /app/cache/catalogs, also container disk.
        "PXS_CACHE_DIR": VIEW_CACHE_MOUNT,
        "PXS_WISE_CACHE": UPSTREAM_CACHE_DIRS[0],
        "PXS_CACHE": CACHE_ROOT,
        "PXS_UPSTREAM_CACHE_DIRS": ":".join(UPSTREAM_CACHE_DIRS),
    },
)
# Requests are mostly light polling; builds run on threads inside the process.
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    from pxs.api import create_app

    # Volume writes persist through Modal's background commits (every few seconds, and a
    # final one at container shutdown). With a single container there is nothing to reload.
    return create_app()


# ---- Archive uptime -------------------------------------------------------------------
# `archive_watch` probes each archive once every 5 minutes (pxs.api.archivestatus) and keeps
# 30 days of checks in a modal.Dict, one key per UTC day plus a small index (layout in
# pxs.archivehistory). `archive_status` only reads that Dict and answers /api/archives with a
# CDN cache header; the site routes that one path to it (PXS_STATUS_ORIGIN,
# web/api/archives.js), so the indicator never starts `web`.

archive_store = modal.Dict.from_name("pxs-archive-history", create_if_missing=True)


@app.function(schedule=modal.Period(minutes=5), cpu=0.125, memory=256, timeout=60,
              region="us-east")
def archive_watch() -> None:
    import time

    from pxs.api.archivestatus import run_probes
    from pxs.archivehistory import save_run

    save_run(archive_store, run_probes(), time.time())


@app.function(cpu=0.125, memory=256, timeout=30, region="us-east", max_containers=3,
              secrets=[modal.Secret.from_name("pxs-proxy")])  # PXS_PROXY_SECRET, as for `web`
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def archive_status():
    from pxs.archivehistory import status_app

    return status_app(lambda: archive_store)


# ---- Gallery builds -------------------------------------------------------------------
# `modal run deploy/modal_app.py::gallery --slugs "a b c"` builds gallery targets in
# parallel, one container each, with the frame index mounted. Each target is written to
# its own directory on the `pxs-gallery` volume (with a one-entry index.json), so parallel
# builds cannot overwrite each other; fetch with `modal volume get pxs-gallery / <dir>/`.

GALLERY_MOUNT = "/gallery"
# The published manifests (not their images), for `--catalogs-from` when the catalogue
# services are down. Mounted at run time on the gallery job only, so the API image is unchanged.
PUBLISHED_DIR = f"{APP_DIR}/published"
gallery_image = image.add_local_dir(
    REPO / "web" / "gallery", PUBLISHED_DIR,
    ignore=lambda p: p.suffix != "" and p.name != "manifest.json")
gallery_volume = modal.Volume.from_name("pxs-gallery", create_if_missing=True)


@app.function(
    cpu=8.0,
    memory=8192,
    timeout=3600,
    region="us-east",
    image=gallery_image,
    volumes={GALLERY_MOUNT: gallery_volume, INDEX_MOUNT: index_volume.read_only()},
    env={"PXS_SPHEREX_INDEX": INDEX_MOUNT, "PXS_SPHEREX_INDEX_SIA_TAIL": "1",
         "PXS_PROCESSES": PXS_PROCESSES},
)
def gallery_build(slug: str, tag: str = "", reuse_catalogs: bool = False) -> dict:
    """Build one gallery target; returns plain values only. `tag` keeps trial builds apart;
    `reuse_catalogs` falls back to the published Gaia and CatWISE lists if the queries fail."""
    import subprocess
    import time

    start = time.monotonic()
    out = f"{GALLERY_MOUNT}/{tag}/{slug}" if tag else f"{GALLERY_MOUNT}/{slug}"
    run = subprocess.run(
        [sys.executable, "-m", "pxs.build", "--target", slug, "--out", out,
         *(("--catalogs-from", PUBLISHED_DIR) if reuse_catalogs else ())],
        cwd=APP_DIR, capture_output=True, text=True, check=False)
    gallery_volume.commit()
    return {"slug": slug, "code": run.returncode, "seconds": round(time.monotonic() - start),
            "log_tail": (run.stderr or run.stdout)[-1200:]}


@app.local_entrypoint()
def gallery(slugs: str, tag: str = "", reuse_catalogs: bool = False) -> None:
    names = [s for s in slugs.split() if s.replace("-", "").isalnum()]
    if tag and not tag.replace("-", "").isalnum():
        raise SystemExit("tag: letters, digits and dashes only")
    for result in gallery_build.starmap([(n, tag, reuse_catalogs) for n in names], return_exceptions=True):
        print(result)
