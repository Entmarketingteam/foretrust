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
    from app.connectors.registry import get_connector
    from app.proxy import proxy_manager
    from app.browser import create_browser
    from app.pipeline.distress_scorer import score_leads
    from app.storage.supabase_client import insert_leads, insert_source_run
    from app.storage.csv_exporter import export_leads_csv
    from app.storage.sheets_exporter import export_leads_sheets

    connector = get_connector(source_key)
    proxy_session = proxy_manager.create_session()
    params = params or {}

    logger.info("[scheduler] Starting %s", source_key)

    async with create_browser(proxy_session=proxy_session, headless=True) as browser:
        leads, run = await connector.run(browser, params, proxy_session)

    # Score leads
    if leads:
        leads = score_leads(leads)

    # Store in all three destinations
    if leads:
        await insert_leads(leads)
        export_leads_csv(leads, source_key)
        export_leads_sheets(leads, source_key)

    # Log the run
    await insert_source_run(run)

    logger.info(
        "[scheduler] %s complete: found=%d, new=%d, status=%s",
        source_key, run.records_found, run.records_new, run.status.value,
    )


def setup_scheduler() -> None:
    """Register all connector cron jobs based on their default_schedule."""
    from app.connectors.registry import list_connectors

    connectors = list_connectors()

    for source_key, cls in connectors.items():
        schedule = cls.default_schedule
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
