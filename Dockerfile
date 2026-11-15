# Live lookup service (pxs.api). Slim image, non-root, uvicorn on $PORT.
#   docker build -t pxs-api .
#   docker run -p 8000:8000 -e PXS_ALLOWED_ORIGINS=https://your.site -v pxs-cache:/app/cache pxs-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PORT=8000 \
    PXS_CACHE_DIR=/app/cache/api \
    PXS_WISE_CACHE=/app/cache/wise \
    PXS_CACHE=/app/cache \
    PXS_UPSTREAM_CACHE_DIRS=/app/cache/wise:/app/cache/spherex:/app/cache/catalogs

WORKDIR /app

# Locked runtime dependencies only (no dev group), installed before the code for layer caching.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.16 \
 && uv sync --frozen --no-dev --no-install-project \
 && pip uninstall -y uv

# Run from the source tree: pxs reads data/templates relative to the repository root.
COPY src ./src
COPY data ./data

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin pxs \
 && mkdir -p /app/cache \
 && chown -R pxs:pxs /app/cache
USER pxs

EXPOSE 8000
# One worker: jobs, the queue and rate limits live in this process's memory.
# --no-proxy-headers: the app decides whether to trust X-Forwarded-For (PXS_TRUST_PROXY).
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn --factory pxs.api:create_app --host 0.0.0.0 --port \"${PORT}\" --workers 1 --no-proxy-headers"]
