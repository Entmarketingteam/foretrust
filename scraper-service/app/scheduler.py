"""APScheduler cron definitions for automated scraper runs.

Each connector declares a default_schedule cron expression.
The scheduler boots with the FastAPI app and runs jobs in the background.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_connector_job(source_key: str, params: dict | None = None) -> None:
    """Execute a single connector run end-to-end."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        force=True,
    )
    from app.connectors.registry import get_connector
    from app.proxy import proxy_manager
    from app.browser import create_browser
    from app.pipeline.distress_scorer import score_leads
    from app.storage.supabase_client import insert_leads, insert_source_run
    from app.storage.csv_exporter import export_leads_csv
    from app.storage.sheets_exporter import export_leads_sheets

    connector = get_connector(source_key)
    params = params or {}
    proxy_session = (
        None
        if params.get("no_proxy")
        else proxy_manager.create_session()
    )
    leads: list = []
    run = None

    logger.info("[scheduler] Starting %s", source_key)

    try:
        async with create_browser(proxy_session=proxy_session, headless=True) as browser:
            leads, run = await connector.run(browser, params, proxy_session)

        # Score leads
        if leads:
            leads = score_leads(leads)

        # Store in all three destinations concurrently
        if leads:
            await asyncio.gather(
                insert_leads(leads),
                asyncio.to_thread(export_leads_csv, leads, source_key),
                asyncio.to_thread(export_leads_sheets, leads, source_key),
            )

        logger.info(
            "[scheduler] %s complete: found=%d, new=%d, status=%s",
            source_key,
            run.records_found if run else 0,
            run.records_new if run else 0,
            run.status.value if run else "unknown",
        )
    except Exception as exc:
        logger.error("[scheduler] %s failed: %s", source_key, exc)
        if run:
            from app.models import SourceRunStatus
            run.status = SourceRunStatus.ERROR
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
    finally:
        # Always persist the audit log
        if run:
            await insert_source_run(run)


async def job_gis_address_enrichment() -> None:
    """Scheduled background job to backfill property addresses for leads using county GIS."""
    logger.info("[scheduler] Starting GIS Address Enrichment background job...")
    try:
        from app.pipeline.gis_address_enrichment import enrich_all_counties_gis
        results = await enrich_all_counties_gis()
        logger.info("[scheduler] GIS Address Enrichment complete: %s", results)
    except Exception as exc:
        logger.error("[scheduler] GIS Address Enrichment job failed: %s", exc)


async def job_google_alerts_probate() -> None:
    """Scheduled background job to run the Google Alerts / Probate Sourcing Agent."""
    logger.info("[scheduler] Starting Google Alerts / Probate Sourcing Agent background job...")
    try:
        from app.pipeline.agentic.google_alerts_agent import GoogleAlertsProbateAgent
        from app.browser import create_browser
        async with create_browser(headless=True) as browser:
            agent = GoogleAlertsProbateAgent()
            leads = await agent.run_sweep(browser)
            logger.info("[scheduler] Google Alerts / Probate Sourcing Agent complete: found %d leads", len(leads))
    except Exception as exc:
        logger.error("[scheduler] Google Alerts / Probate Sourcing Agent job failed: %s", exc)


def setup_scheduler() -> None:
    """Register all connector cron jobs based on their default_schedule."""
    from app.connectors.registry import list_connectors

    connectors = list_connectors()

    for source_key, cls in connectors.items():
        schedule = getattr(cls, "default_schedule", "") or ""
        if not schedule:
            logger.info("[scheduler] %s: no schedule (manual only)", source_key)
            continue

        # Parse cron parts
        parts = schedule.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
            )
            scheduler.add_job(
                run_connector_job,
                trigger=trigger,
                args=[source_key],
                id=f"cron_{source_key}",
                name=f"Cron: {source_key}",
                replace_existing=True,
            )
            logger.info("[scheduler] Registered %s: %s", source_key, schedule)
        else:
            logger.warning("[scheduler] Invalid cron for %s: %s", source_key, schedule)

    # Register standalone custom background jobs
    scheduler.add_job(
        job_gis_address_enrichment,
        trigger=CronTrigger(hour="1", minute="0"),
        id="job_gis_address_enrichment",
        name="Background: GIS Address Enrichment",
        replace_existing=True,
    )
    logger.info("[scheduler] Registered Standalone Background: GIS Address Enrichment (Every day at 1:00 AM UTC)")

    scheduler.add_job(
        job_google_alerts_probate,
        trigger=CronTrigger(hour="8", minute="0"),
        id="job_google_alerts_probate",
        name="Background: Google Alerts Probate Agent",
        replace_existing=True,
    )
    logger.info("[scheduler] Registered Standalone Background: Google Alerts Probate Agent (Every day at 8:00 AM UTC)")


def start_scheduler() -> None:
    """Initialize and start the scheduler."""
    setup_scheduler()
    scheduler.start()
    logger.info("[scheduler] Started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] Stopped")
