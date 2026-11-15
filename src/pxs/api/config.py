"""Service settings, read once from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Bump by hand whenever a pipeline change alters built views. It is part of every cache
# key, so views cached by an older build are never served after the bump.
PIPELINE_VERSION = "1"


class ConfigError(ValueError):
    """An environment variable has a value the service cannot use."""


@dataclass(frozen=True)
class Settings:
    cache_dir: Path = REPO / "cache" / "api"
    cache_max_bytes: int = 2 * 1024**3
    max_builds: int = 2
    queue_cap: int = 8
    build_timeout_s: float = 240.0
    rate_limit: int = 6
    rate_window_s: float = 600.0
    trust_proxy: bool = False
    # Shared with the site's proxy (web/middleware.js). When set, a request carrying it may
    # name its client in x-pxs-client-ip and forwarded headers are never read. Kept out of repr.
    proxy_secret: str = field(default="", repr=False)
    require_proxy: bool = False  # refuse (403) requests without the secret, except health
    allowed_origins: tuple[str, ...] = ()
    resolve_timeout_s: float = 4.0
    job_ttl_s: float = 3600.0
    degraded_ttl_s: float = 600.0  # how long a view built from partial data is kept
    resolve_limit: int = 20  # name lookups per client per window
    resolve_window_s: float = 600.0
    max_abandoned: int = 4  # timed-out builds whose threads still run; at the cap: unhealthy
    exit_when_stuck: bool = False  # opt-in last resort: exit the process when at that cap
    exit_grace_s: float = 30.0
    upstream_cache_dirs: tuple[Path, ...] = ()  # swept to the budget after each build
    upstream_cache_max_bytes: int = 1024 * 1024**2


def _int(env: Mapping[str, str], name: str, default: int, low: int = 1) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < low:
        raise ConfigError(f"{name} must be at least {low}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if not value > 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value


def _origins(raw: str) -> tuple[str, ...]:
    out = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    if "*" in out:
        raise ConfigError("PXS_ALLOWED_ORIGINS must list origins; a wildcard is not allowed")
    bad = [o for o in out if not o.startswith(("https://", "http://"))]
    if bad:
        raise ConfigError(f"PXS_ALLOWED_ORIGINS entries must start with http(s)://: {bad}")
    return out


MIN_SECRET_LEN = 32


def _proxy_secret(env: Mapping[str, str]) -> str:
    """PXS_PROXY_SECRET, checked for length; the value never appears in an error."""
    secret = env.get("PXS_PROXY_SECRET", "").strip()
    if secret and len(secret) < MIN_SECRET_LEN:
        raise ConfigError(f"PXS_PROXY_SECRET must be at least {MIN_SECRET_LEN} characters")
    if env.get("PXS_REQUIRE_PROXY", "") == "1" and not secret:
        raise ConfigError("PXS_REQUIRE_PROXY=1 needs PXS_PROXY_SECRET")
    return secret


def from_env(env: Mapping[str, str] | None = None) -> Settings:
    """Settings from `env` (default os.environ). Raises ConfigError on bad values."""
    env = os.environ if env is None else env
    d = Settings()
    cache = env.get("PXS_CACHE_DIR")
    return Settings(
        cache_dir=Path(cache) if cache else d.cache_dir,
        cache_max_bytes=_int(env, "PXS_CACHE_MAX_MB", d.cache_max_bytes // 1024**2) * 1024**2,
        max_builds=_int(env, "PXS_MAX_BUILDS", d.max_builds),
        queue_cap=_int(env, "PXS_QUEUE_CAP", d.queue_cap, low=0),
        build_timeout_s=_float(env, "PXS_BUILD_TIMEOUT_S", d.build_timeout_s),
        rate_limit=_int(env, "PXS_RATE_LIMIT", d.rate_limit),
        rate_window_s=_float(env, "PXS_RATE_WINDOW_S", d.rate_window_s),
        trust_proxy=env.get("PXS_TRUST_PROXY", "") == "1",
        proxy_secret=_proxy_secret(env),
        require_proxy=env.get("PXS_REQUIRE_PROXY", "") == "1",
        allowed_origins=_origins(env.get("PXS_ALLOWED_ORIGINS", "")),
        resolve_timeout_s=_float(env, "PXS_RESOLVE_TIMEOUT_S", d.resolve_timeout_s),
        degraded_ttl_s=_float(env, "PXS_DEGRADED_TTL_S", d.degraded_ttl_s),
        resolve_limit=_int(env, "PXS_RESOLVE_LIMIT", d.resolve_limit),
        resolve_window_s=_float(env, "PXS_RESOLVE_WINDOW_S", d.resolve_window_s),
        max_abandoned=_int(env, "PXS_MAX_ABANDONED", d.max_abandoned),
        exit_when_stuck=env.get("PXS_EXIT_WHEN_STUCK", "") == "1",
        exit_grace_s=_float(env, "PXS_EXIT_GRACE_S", d.exit_grace_s),
        upstream_cache_dirs=tuple(Path(p) for p in
                                  env.get("PXS_UPSTREAM_CACHE_DIRS", "").split(os.pathsep) if p),
        upstream_cache_max_bytes=_int(env, "PXS_UPSTREAM_CACHE_MAX_MB",
                                      d.upstream_cache_max_bytes // 1024**2) * 1024**2,
    )
