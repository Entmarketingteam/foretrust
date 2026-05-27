"""FastAPI entrypoint for the Foretrust scraper service.

Endpoints:
  GET  /health           - Healthcheck
  GET  /connectors       - List registered connectors
  POST /run/{source_key} - Trigger a connector run on demand
  GET  /runs             - Recent run history
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

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
    if not hmac.compare_digest(token, settings.scraper_shared_token):
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
    background_tasks: BackgroundTasks,
    body: RunRequest | None = None,
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
    background_tasks.add_task(run_connector_job, source_key, params)

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


# -----------------------------------------------------------------------
# Full Pipeline — chains all free KY sources end-to-end
# -----------------------------------------------------------------------

class PipelineRequest(BaseModel):
    counties: list[str] = []           # defaults to all 8 target counties
    limit_per_source: int = 100        # max records per connector
    sources: list[str] = []            # optional: subset of sources to run


@app.post("/pipeline/full")
async def trigger_full_pipeline(
    background_tasks: BackgroundTasks,
    body: PipelineRequest | None = None,
    authorization: str | None = Header(None),
):
    """Run the complete free-source KY pipeline end-to-end.

    Chains: KCOJ → GIS → PVA (all counties) → Master Commissioner →
            Delinquent Tax → Legal Notices → Cross-reference → Score → Persist

    Runs as a background task — returns immediately with job ID.
    """
    _check_auth(authorization)

    params: dict[str, Any] = {}
    if body:
        if body.counties:
            params["counties"] = body.counties
        params["limit_per_source"] = body.limit_per_source

    background_tasks.add_task(_run_pipeline_task, params)

    return {
        "status": "accepted",
        "message": "Full pipeline running in background",
        "params": params,
    }


async def _run_pipeline_task(params: dict[str, Any]) -> None:
    """Background task that runs the full pipeline with a fresh browser."""
    from app.browser import create_browser
    from app.pipeline.orchestrator import run_full_pipeline

    logger.info("[pipeline] Starting full pipeline run")
    try:
        async with create_browser() as browser:
            leads, summary = await run_full_pipeline(browser, params)
            logger.info(
                "[pipeline] Complete: %d leads, %d hot. Summary: %s",
                summary.get("total_leads", 0),
                summary.get("hot_leads", 0),
                {k: v for k, v in summary.get("stages", {}).items()
                 if isinstance(v, dict) and "count" in v},
            )
    except Exception as exc:
        logger.error("[pipeline] Full pipeline run failed: %s", exc)


class PreMlsPipelineRequest(BaseModel):
    counties: list[str] = []
    limit_per_source: int = 100
    gis_limit: int = 50
    party_search_limit: int = 30
    run_ecclix: bool = True
    ecclix_limit: int = 40


class EcclixDayPassRequest(BaseModel):
    """Burn eCCLIX day pass — see docs/KY-DISTRESSED-LEAD-MAP.md for modes."""
    counties: list[str] = []
    limit: int = 40
    addresses: list[str] = []
    mode: str = "deep_portal_search"  # deep_portal_search | full_day_pass | pre_mls_sprint | lp_recent
    days_back: int = 60
    tax_year: int = 2025
    download_documents: bool = True


@app.post("/pipeline/pre-mls")
async def trigger_pre_mls_pipeline(
    background_tasks: BackgroundTasks,
    body: PreMlsPipelineRequest | None = None,
    authorization: str | None = Header(None),
):
    """Run the distress-first pre-MLS pipeline.

    Chains: Legal Notices → Master Commissioner → Delinquent Tax →
            KCOJ party searches (from notices) → GIS → PVA → eCCLIX (if creds) →
            Cross-reference → Score → Persist
    """
    _check_auth(authorization)

    params: dict[str, Any] = {}
    if body:
        if body.counties:
            params["counties"] = body.counties
        params["limit_per_source"] = body.limit_per_source
        params["gis_limit"] = body.gis_limit
        params["party_search_limit"] = body.party_search_limit
        params["run_ecclix"] = body.run_ecclix
        params["ecclix_limit"] = body.ecclix_limit

    background_tasks.add_task(_run_pre_mls_pipeline_task, params)

    return {
        "status": "accepted",
        "message": "Pre-MLS pipeline running in background",
        "params": params,
    }


async def _run_pre_mls_pipeline_task(params: dict[str, Any]) -> None:
    """Background task for the pre-MLS pipeline."""
    from app.browser import create_browser
    from app.pipeline.pre_mls_orchestrator import run_pre_mls_pipeline

    logger.info("[pipeline] Starting pre-MLS pipeline run")
    try:
        async with create_browser() as browser:
            leads, summary = await run_pre_mls_pipeline(browser, params)
            logger.info(
                "[pipeline] Pre-MLS complete: %d leads, %d hot. Summary: %s",
                summary.get("total_leads", 0),
                summary.get("hot_leads", 0),
                {k: v for k, v in summary.get("stages", {}).items()
                 if isinstance(v, dict) and "count" in v},
            )
    except Exception as exc:
        logger.error("[pipeline] Pre-MLS pipeline run failed: %s", exc)


@app.post("/pipeline/ecclix")
async def trigger_ecclix_day_pass(
    background_tasks: BackgroundTasks,
    body: EcclixDayPassRequest | None = None,
    authorization: str | None = Header(None),
):
    """Run eCCLIX batch only — use during an active day pass."""
    _check_auth(authorization)
    params: dict[str, Any] = {
        "mode": "deep_portal_search",
        "download_documents": True,
        "full_extract": True,
        "days_back": 120,
        "max_pages": 100,
        "tax_year": 2025,
    }
    if body:
        if body.counties:
            params["counties"] = body.counties
        params["max_documents_per_county"] = body.limit
        params["mode"] = body.mode
        params["days_back"] = body.days_back
        params["tax_year"] = body.tax_year
        params["download_documents"] = body.download_documents
        if body.addresses:
            params["mode"] = "address"
            params["addresses"] = body.addresses
            params["use_pending_leads"] = False
    background_tasks.add_task(run_connector_job, "ecclix_batch", params)
    return {
        "status": "accepted",
        "message": "eCCLIX day-pass batch running in background",
        "params": params,
    }


class EcclixCsvImportRequest(BaseModel):
    """Paths on scraper host or JSON row payloads from manual export."""
    paths: list[str] = []
    county: str = "scott"
    tier: str = "A"
    min_amount: float = 500.0
    persist: bool = True


class SignalDigestRequest(BaseModel):
    """LP + probate + code violations + water → email CSVs for skip trace / drive-by."""
    counties: list[str] = []
    send_email: bool = True
    persist: bool = True
    run_ecclix: bool = True
    run_kcoj: bool = True
    run_legal_notices: bool = True
    run_water: bool = True
    water_foia_csv: str = ""  # path to manual GMWSS disconnect CSV
    download_documents: bool = False
    days_back: int = 365


@app.post("/pipeline/signal-digest")
async def trigger_signal_digest(
    background_tasks: BackgroundTasks,
    body: SignalDigestRequest | None = None,
    authorization: str | None = Header(None),
):
    """Full signal stack + categorized email (lis pendens, probate, code, water)."""
    _check_auth(authorization)
    params: dict[str, Any] = {
        "counties": ["scott", "bourbon", "woodford", "franklin"],
        "ecclix_mode": "signal_intel",
        "send_email": True,
        "persist": True,
    }
    if body:
        params.update(body.model_dump(exclude_none=True))

    async def _task() -> None:
        from app.browser import create_browser
        from app.pipeline.signal_intel import run_signal_intel_pipeline

        async with create_browser() as browser:
            result = await run_signal_intel_pipeline(browser, params)
            logger.info("[pipeline] signal digest: %s", result.get("summary"))

    background_tasks.add_task(_task)
    return {"status": "accepted", "message": "Signal digest running", "params": params}


@app.post("/pipeline/best-deals")
async def trigger_best_deals_report(
    background_tasks: BackgroundTasks,
    enrich_pva: bool = False,
    authorization: str | None = Header(None),
):
    """Rank pre-MLS / short-sale / 203k buckets → exports/best-deals/*.md"""
    _check_auth(authorization)

    async def _task() -> None:
        from app.browser import create_browser
        from app.pipeline.deal_package import build_best_deals_package

        async with create_browser() as browser:
            await build_best_deals_package(browser, enrich_pva=enrich_pva)

    background_tasks.add_task(_task)
    return {"status": "accepted", "message": "Best deals report building", "enrich_pva": enrich_pva}


@app.post("/ingest/ecclix-csv")
async def ingest_ecclix_csv(
    body: EcclixCsvImportRequest,
    authorization: str | None = Header(None),
):
    """Import table-scraper delinquent tax CSVs → ft_leads (ecclix_csv_import)."""
    _check_auth(authorization)
    from app.ingest.ecclix_csv import import_paths
    from app.storage.supabase_client import insert_leads

    if not body.paths:
        raise HTTPException(400, "paths required (absolute paths on scraper container/host)")

    leads, summary = import_paths(
        body.paths,
        county=body.county,
        tier=body.tier,
        min_amount=body.min_amount,
    )
    persisted = 0
    if body.persist and leads:
        persisted = await insert_leads(leads)

    return {
        "status": "ok",
        "summary": summary,
        "persisted": persisted,
        "top_leads": [
            {
                "bill_number": l.case_id,
                "owner_name": l.owner_name,
                "property_address": l.property_address,
                "amount_due": l.estimated_value,
                "hot_score": l.hot_score,
                "best_strategy": (l.raw_payload or {}).get("best_strategy"),
            }
            for l in leads[:20]
        ],
    }


# -----------------------------------------------------------------------
# Clerk PDFs (served from scraper volume — used by Node backend on Railway)
# -----------------------------------------------------------------------

@app.get("/clerk-document")
async def serve_clerk_document(
    path: str,
    authorization: str | None = Header(None),
):
    """Stream a clerk PDF from exports/ecclix. Path must resolve under export root."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.storage.clerk_documents import _export_root

    _check_auth(authorization)
    if not path or not path.strip():
        raise HTTPException(400, "path query param required")

    export_root = _export_root().resolve()
    requested = Path(path.strip()).expanduser()
    if not requested.is_absolute():
        requested = (export_root / requested).resolve()
    else:
        requested = requested.resolve()

    try:
        requested.relative_to(export_root)
    except ValueError:
        raise HTTPException(403, "Path outside clerk export directory")

    if not requested.is_file():
        raise HTTPException(404, "Document not found on scraper volume")

    return FileResponse(
        requested,
        media_type="application/pdf",
        filename=requested.name,
    )
