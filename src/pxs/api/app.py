"""The ASGI app: routes, CORS, safe error responses."""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import tomllib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from pxs.api import config
from pxs.api.bodies import BodyParams, BodyResolver, clean_body_name
from pxs.api.bodyrunner import index_tag, make_body_builder
from pxs.api.cache import ViewCache
from pxs.api.jobs import BuildFn, JobManager, QueueFull
from pxs.api.params import ParamError, ViewParams, clean_name, parse_view, single_values
from pxs.api.ratelimit import RateLimiter, client_key
from pxs.api.resolve import NOT_FOUND, Resolver
from pxs.api.runner import default_builder, source_status
from pxs.api.sweep import sweep

log = logging.getLogger("pxs.api")

NO_STORE = {"Cache-Control": "no-store"}
IMMUTABLE = "public, max-age=31536000, immutable"
BUSY_RETRY_S = 30
SBDB_RETRY_S = 30

try:
    VERSION = version("planet-x-spherex")
except PackageNotFoundError:  # run from the source tree (the container does this)
    try:
        VERSION = tomllib.loads((config.REPO / "pyproject.toml").read_text())["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        VERSION = "unknown"


def _json(body: dict, status: int = 200, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**NO_STORE, **(headers or {})})


def _error(message: str, status: int, retry_after: int | None = None) -> JSONResponse:
    body: dict = {"error": message}
    headers = {}
    if retry_after is not None:
        body["retry_after_s"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return _json(body, status, headers)


PROXY_SECRET_HEADER = "x-pxs-proxy-secret"
CLIENT_IP_HEADER = "x-pxs-client-ip"
NOT_PROXIED = "This service answers only through the project site."


def proxied(request: Request, secret: str) -> bool:
    """True when `secret` is set and the request carries it (compared in constant time)."""
    if not secret:
        return False
    sent = request.headers.get(PROXY_SECRET_HEADER, "")
    return hmac.compare_digest(sent.encode("utf-8"), secret.encode("utf-8"))


def _proxied_client(request: Request) -> str | None:
    """The proxy's x-pxs-client-ip when it is one valid address, else None."""
    try:
        return str(ipaddress.ip_address(request.headers.get(CLIENT_IP_HEADER, "").strip()))
    except ValueError:
        return None


def client_address(request: Request, trust_proxy: bool, proxy_secret: str = "") -> str:
    """The rate-limit key. With a proxy secret configured: the proxy's x-pxs-client-ip when
    the request carries the secret and names a valid address, otherwise the socket peer;
    forwarded headers are never read. Without one: the rightmost X-Forwarded-For entry when
    `trust_proxy` (added by our own proxy), otherwise the socket peer. IPv6 collapses to its
    /64 and IPv4-mapped to IPv4."""
    if proxy_secret:
        ip = _proxied_client(request) if proxied(request, proxy_secret) else None
        if ip:
            return client_key(ip)
    elif trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return client_key(hops[-1])
    return client_key(request.client.host) if request.client else "unknown"


def _with_name(manifest: dict, name: str | None) -> dict:
    return {**manifest, "target": {**manifest["target"], "name": name}} if name else manifest


def _query_name(request: Request) -> str | None:
    """The optional cosmetic `name` on a status or manifest URL; invalid names are ignored."""
    try:
        return clean_name(request.query_params.get("name"))
    except ParamError:
        return None


def _prefixed(node: Any, prefix: str) -> Any:
    """A copy of `node` with every "image" path under it prefixed."""
    if isinstance(node, dict):
        return {k: prefix + v if k == "image" and isinstance(v, str) else _prefixed(v, prefix)
                for k, v in node.items()}
    if isinstance(node, list):
        return [_prefixed(v, prefix) for v in node]
    return node


def cached_manifest(cache: ViewCache, params: ViewParams | BodyParams) -> dict:
    """The cached manifest with image paths made relative to /api/view and the name set."""
    m = json.loads((cache.views / params.key / "manifest.json").read_text())
    prefix = f"views/{params.key}/"
    m["frames"] = [{**f, "image": prefix + f["image"]} for f in m["frames"]]
    if "solar_system" in m:  # a body view also lists its body-centred images there
        m["solar_system"] = _prefixed(m["solar_system"], prefix)
    m["target"] = {**m["target"], "name": params.name}
    return m


ServeFn = Callable[[Request, ViewParams | BodyParams], Response]


def _build_routes(app: FastAPI, s: config.Settings, cache: ViewCache, jobs: JobManager,
                  limiter: RateLimiter) -> ServeFn:
    def status_url(job_id: str, name: str | None) -> str:
        return f"/api/jobs/{job_id}" + (f"?name={quote(name, safe='')}" if name else "")

    @app.get("/api/view")
    def view(request: Request) -> Response:
        try:
            params = parse_view(request.query_params.multi_items())
        except ParamError as exc:
            return _error(str(exc), 422)
        return serve_or_start(request, params)

    def serve_or_start(request: Request, params: ViewParams | BodyParams) -> Response:
        """The cached manifest (200), or the build job for it (202), started if need be."""
        if cache.has(params.key):
            cache.touch(params.key)
            control = ("no-store" if cache.is_degraded(params.key)
                       else "public, max-age=86400")
            return JSONResponse(cached_manifest(cache, params),
                                headers={"Cache-Control": control})
        job = jobs.active(params.key)
        if job is None:
            client = client_address(request, s.trust_proxy, s.proxy_secret)
            wait = limiter.try_acquire(client)
            if wait:
                return _error("You have started many new views recently. Please wait before "
                              "starting another; views already built still open.", 429, wait)
            try:
                job, created = jobs.submit(params)
            except QueueFull:
                limiter.refund(client)
                return _error("The server is busy building other views. Try again shortly.",
                              503, BUSY_RETRY_S)
            if not created:  # joined a job another request started meanwhile
                limiter.refund(client)
        return _json({"job": job.id, "status_url": status_url(job.id, params.name)}, 202)

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str, request: Request) -> Response:
        job = jobs.get(job_id) if len(job_id) <= 32 else None
        if job is None:
            return _error("That job is not known. The server may have restarted; "
                          "search again.", 404)
        body = job.status(jobs.queue_position(job))
        name = _query_name(request)
        if body["manifest_url"] and name:  # carry the requester's own name to the manifest
            body["manifest_url"] += f"?name={quote(name, safe='')}"
        return _json(body)

    return serve_or_start


def _body_answer(request: Request, s: config.Settings, limiter: RateLimiter,
                 resolver: BodyResolver) -> dict | Response:
    """The resolver's answer for ?name=, or an error Response (422, 429)."""
    try:
        q = single_values(request.query_params.multi_items(), frozenset({"name"}))
        name = clean_body_name(q.get("name"))
    except ParamError as exc:
        return _error(str(exc), 422)
    answer = resolver.peek(name)  # curated or remembered: no upstream call, no quota
    if answer is None:
        client = client_address(request, s.trust_proxy, s.proxy_secret)
        wait = limiter.try_acquire(client)
        if wait:
            return _error("Too many name lookups. Please wait before looking up another body.",
                          429, wait)
        answer = resolver(name)
    return answer


def _unresolved(answer: dict, status: int) -> Response:
    """A name that is not one body: 503 when SBDB is down, else `status` with suggestions."""
    if answer.get("unavailable"):
        return _error(answer["message"], 503, SBDB_RETRY_S)
    key = "message" if status == 200 else "error"
    body = {key: answer["message"], "did_you_mean": answer["did_you_mean"]}
    return _json({"resolved": False, **body} if status == 200 else body, status)


def _body_routes(app: FastAPI, s: config.Settings, resolve_limiter: RateLimiter,
                 resolver: BodyResolver, serve_or_start: ServeFn) -> None:
    @app.get("/api/body/resolve")
    def body_resolve(request: Request) -> Response:
        answer = _body_answer(request, s, resolve_limiter, resolver)
        if isinstance(answer, Response):
            return answer
        if not answer["resolved"]:
            return _unresolved(answer, 200)
        return _json({k: answer[k] for k in ("resolved", "designation", "name", "kind")})

    @app.get("/api/body")
    def body_view(request: Request) -> Response:
        answer = _body_answer(request, s, resolve_limiter, resolver)
        if isinstance(answer, Response):
            return answer
        if not answer["resolved"]:
            return _unresolved(answer, 404)
        params = BodyParams(answer["designation"], answer["name"], answer["horizons"],
                            answer["kind"], index_tag(), datetime.now(UTC).date().isoformat())
        return serve_or_start(request, params)


def _read_routes(app: FastAPI, s: config.Settings, cache: ViewCache, jobs: JobManager,
                 limiter: RateLimiter, resolve_limiter: RateLimiter,
                 resolver: Resolver) -> None:
    @app.get("/api/views/{key}/{rel:path}")
    def view_file(key: str, rel: str, request: Request) -> Response:
        path = cache.file(key, rel)
        if path is None:
            return _error("Not found.", 404)
        cache.touch(key)
        control = "no-store" if cache.is_degraded(key) else IMMUTABLE
        name = _query_name(request) if rel == "manifest.json" else None
        if name:
            manifest = _with_name(json.loads(path.read_text()), name)
            return JSONResponse(manifest, headers={"Cache-Control": control})
        return FileResponse(path, headers={"Cache-Control": control})

    @app.get("/api/health")
    def health(request: Request) -> Response:
        ok = jobs.healthy()
        if s.require_proxy and not proxied(request, s.proxy_secret):
            return _json({"status": "ok" if ok else "unhealthy"}, 200 if ok else 503)
        body = {"status": "ok" if ok else "unhealthy", "version": VERSION,
                "pipeline": config.PIPELINE_VERSION, "cache": cache.stats(),
                "jobs": jobs.counts(), "sources": app.state.sources,
                # distinct client keys seen in the window: a count, never the addresses
                "clients": {"build": limiter.clients_seen(),
                            "resolve": resolve_limiter.clients_seen()}}
        return _json(body, 200 if ok else 503)

    @app.get("/api/resolve")
    def resolve(request: Request) -> Response:
        try:
            q = single_values(request.query_params.multi_items(), frozenset({"name"}))
            name = clean_name(q.get("name"))
        except ParamError as exc:
            return _error(str(exc), 422)
        if name is None:
            return _error("'name' is required.", 422)
        answer = resolver.peek(name)  # a remembered answer costs no upstream call or quota
        if answer is None:
            client = client_address(request, s.trust_proxy, s.proxy_secret)
            wait = resolve_limiter.try_acquire(client)
            if wait:
                return _error("Too many name lookups. Please wait, or enter coordinates.",
                              429, wait)
            answer = resolver(name)
        return _json(answer if answer.get("resolved") else {"resolved": False,
                                                            "message": NOT_FOUND})


def _dispatch(view_fn: BuildFn, body_fn: BuildFn) -> BuildFn:
    """One build function for the shared job pool: body requests go to `body_fn`."""
    def run(params: Any, out_dir: Any, report: Any) -> dict:
        return (body_fn if isinstance(params, BodyParams) else view_fn)(params, out_dir, report)
    return run


def create_app(settings: config.Settings | None = None, build_fn: BuildFn | None = None,
               resolver: Resolver | None = None, body_build_fn: BuildFn | None = None,
               body_resolver: BodyResolver | None = None) -> FastAPI:
    """Build the app. Tests inject the build functions and resolvers; production reads the env."""
    s = settings or config.from_env()
    if not logging.getLogger().handlers:  # under uvicorn: show job lifecycles at INFO
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cache = ViewCache(s.cache_dir, s.cache_max_bytes, s.degraded_ttl_s)
    housekeeping = ((lambda: sweep(s.upstream_cache_dirs, s.upstream_cache_max_bytes))
                    if s.upstream_cache_dirs else None)
    body_fn = body_build_fn or make_body_builder(s.build_timeout_s)
    jobs = JobManager(cache, _dispatch(build_fn or default_builder(), body_fn),
                      max_builds=s.max_builds,
                      queue_cap=s.queue_cap, timeout_s=s.build_timeout_s, ttl_s=s.job_ttl_s,
                      max_abandoned=s.max_abandoned, exit_when_stuck=s.exit_when_stuck,
                      exit_grace_s=s.exit_grace_s, after_build=housekeeping)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.close()

    app = FastAPI(title="Ephemerix live API", version=VERSION, docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(s.allowed_origins),
                       allow_methods=["GET"], allow_headers=[], allow_credentials=False,
                       expose_headers=["Retry-After"], max_age=600)

    @app.middleware("http")
    async def require_proxy(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (s.require_proxy and request.url.path != "/api/health"
                and not proxied(request, s.proxy_secret)):
            return _error(NOT_PROXIED, 403)
        return await call_next(request)

    @app.middleware("http")
    async def harden(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> Response:
        log.exception("unhandled error on %s", request.url.path)
        return _error("Something went wrong on the server.", 500)

    limiter = RateLimiter(s.rate_limit, s.rate_window_s)
    resolve_limiter = RateLimiter(s.resolve_limit, s.resolve_window_s)
    serve_or_start = _build_routes(app, s, cache, jobs, limiter)
    _body_routes(app, s, resolve_limiter, body_resolver or BodyResolver(s.resolve_timeout_s),
                 serve_or_start)
    _read_routes(app, s, cache, jobs, limiter, resolve_limiter,
                 resolver or Resolver(s.resolve_timeout_s))
    app.state.jobs, app.state.cache, app.state.sources = jobs, cache, source_status()
    return app
