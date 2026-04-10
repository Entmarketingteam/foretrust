"""FastAPI entrypoint for the Foretrust scraper service.

Endpoints:
  GET  /health           - Healthcheck
  GET  /connectors       - List registered connectors
  POST /run/{source_key} - Trigger a connector run on demand
  GET  /runs             - Recent run history
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncio

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel

from app.config import settings
from app.scheduler import start_scheduler, stop_scheduler, run_connector_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start scheduler on boot, stop on shutdown."""
    logger.info("Scraper service starting...")
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Scraper service stopped.")


app = FastAPI(
    title="Foretrust Scraper Service",
    version="1.0.0",
    lifespan=lifespan,
)


def _check_auth(authorization: str | None) -> None:
    """Verify the shared bearer token from the Node backend."""
    if not settings.scraper_shared_token:
        return  # No token configured = open (dev mode)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:]
    if token != settings.scraper_shared_token:
        raise HTTPException(403, "Invalid token")


# -----------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "foretrust-scraper",
        "version": "1.0.0",
    }


# -----------------------------------------------------------------------
# Connectors
# -----------------------------------------------------------------------

@app.get("/connectors")
async def list_connectors_endpoint(authorization: str | None = Header(None)):
    _check_auth(authorization)
    from app.connectors.registry import list_connectors

    connectors = list_connectors()
    return {
        "connectors": [
            {
                "source_key": cls.source_key,
                "vertical": cls.vertical.value,
                "jurisdiction": cls.jurisdiction,
                "schedule": cls.default_schedule or "manual",
            }
            for cls in connectors.values()
        ]
    }


# -----------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------

class RunRequest(BaseModel):
    params: dict[str, Any] = {}


@app.post("/run/{source_key}")
async def trigger_run(
    source_key: str,
    body: RunRequest | None = None,
    background_tasks: BackgroundTasks = None,
    authorization: str | None = Header(None),
):
    _check_auth(authorization)

    from app.connectors.registry import get_connector
    try:
        get_connector(source_key)
    except KeyError as exc:
        raise HTTPException(404, str(exc))

    params = body.params if body else {}

    # Dispatch as background task so the endpoint returns immediately
    asyncio.create_task(run_connector_job(source_key, params))

    return {"status": "accepted", "source_key": source_key}


# -----------------------------------------------------------------------
# Runs
# -----------------------------------------------------------------------

@app.get("/runs")
async def list_runs(
    limit: int = 20,
    authorization: str | None = Header(None),
):
    _check_auth(authorization)

    from app.storage.supabase_client import list_source_runs
    runs = await list_source_runs(limit)
    return {"runs": runs}
