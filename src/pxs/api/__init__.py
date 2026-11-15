"""Live lookup service: builds a view manifest for any sky position on demand. Written with
Claude Code.

    uvicorn --factory pxs.api:create_app --port 8000

`GET /api/view` answers 200 with a cached manifest or 202 with a job to poll at
`/api/jobs/<id>`. Finished views live under `PXS_CACHE_DIR` and are served as immutable
files from `/api/views/<key>/`. See deploy/README.md for the environment variables.
"""

from pxs.api.app import create_app

__all__ = ["create_app"]
