"""Abstract base connector contract.

Every data source inherits from BaseConnector and implements fetch() + parse().
Adding a new county or source is one file — no framework changes required.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from playwright.async_api import Browser

from app.models import Lead, RawRecord, SourceRun, SourceRunStatus, Vertical
from app.browser import create_context, check_robots_txt, human_delay
from app.proxy import ProxySession, proxy_manager
from app.pipeline.normalize import normalize_lead

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base for all data-source connectors."""

    source_key: str  # e.g. "kcoj_courtnet"
    vertical: Vertical  # commercial | residential | multifamily
    jurisdiction: str  # e.g. "KY-Fayette"
    base_url: str  # e.g. "https://kcoj.kycourts.net"
    default_schedule: str  # cron expression, e.g. "0 6 * * *"
    respects_robots: bool = True
    max_concurrent_pages: int = 1  # never more than 1 against gov sites

    @abstractmethod
    async def fetch(
        self, browser: Browser, params: dict[str, Any]
    ) -> list[RawRecord]:
        """Scrape raw records from the source. Must be implemented per connector."""
        ...

    @abstractmethod
    def parse(self, raw: RawRecord) -> Lead:
        """Transform a raw record into a normalized Lead."""
        ...

    async def run(
        self,
        browser: Browser,
        params: dict[str, Any] | None = None,
        proxy_session: ProxySession | None = None,
    ) -> tuple[list[Lead], SourceRun]:
        """Execute the full connector pipeline: robots → fetch → parse → normalize → dedupe."""
        params = params or {}
        run = SourceRun(
            source_key=self.source_key,
            proxy_session_id=proxy_session.session_id if proxy_session else None,
        )

        try:
            # 1. Check robots.txt
            if self.respects_robots:
                async with create_context(browser, proxy_session) as ctx:
                    page = await ctx.new_page()
                    allowed = await check_robots_txt(page, self.base_url)
                    if not allowed:
                        run.status = SourceRunStatus.BLOCKED
                        run.error_message = "robots.txt disallows scraping"
                        run.finished_at = datetime.utcnow()
                        logger.warning(
                            "[%s] Aborted: robots.txt disallows", self.source_key
                        )
                        return [], run

            # 2. Fetch raw records
            raw_records = await self.fetch(browser, params)
            run.records_found = len(raw_records)

            # 3. Parse + normalize + dedupe
            leads: list[Lead] = []
            seen_hashes: set[str] = set()

            for raw in raw_records:
                try:
                    lead = self.parse(raw)
                    lead.vertical = self.vertical
                    lead.source_key = self.source_key
                    lead = normalize_lead(lead)

                    if lead.dedupe_hash not in seen_hashes:
                        seen_hashes.add(lead.dedupe_hash)
                        leads.append(lead)
                except Exception as exc:
                    logger.warning(
                        "[%s] Failed to parse record: %s", self.source_key, exc
                    )

            run.records_new = len(leads)
            run.status = SourceRunStatus.OK
            run.finished_at = datetime.utcnow()

            logger.info(
                "[%s] Run complete: found=%d, new=%d",
                self.source_key, run.records_found, run.records_new,
            )
            return leads, run

        except Exception as exc:
            run.status = SourceRunStatus.ERROR
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            logger.error("[%s] Run failed: %s", self.source_key, exc)
            return [], run
