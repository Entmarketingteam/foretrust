"""eCCLIX multi-county batch runner.

Batch-scrapes deed, will, and mortgage records across eCCLIX counties
(Scott, Clark, Madison, Bourbon, Woodford) using a single day-pass.

Triggering: on-demand once lead queue exceeds ECCLIX_BATCH_THRESHOLD.
Operator buys a day pass (~$15-30), enters creds in Doppler, then
triggers via POST /api/foretrust/leads/scrape {source_key: "ecclix_batch"}.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, SourceRunStatus, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto
from app.captcha import detect_and_solve_captcha
from app.config import settings

logger = logging.getLogger(__name__)

# eCCLIX portals by county
ECCLIX_URLS: dict[str, str] = {
    "scott": "https://scottky.ecclix.com",
    "clark": "https://clarkky.ecclix.com",
    "madison": "https://madisonky.ecclix.com",
    "bourbon": "https://bourbonky.ecclix.com",
    "woodford": "https://woodfordky.ecclix.com",
}


@register
class ECCLIXBatchConnector(BaseConnector):
    source_key = "ecclix_batch"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://scottky.ecclix.com"  # primary
    default_schedule = ""  # on-demand only
    respects_robots = False  # Paid authenticated service — operator has a valid day-pass license

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        counties = params.get("counties", settings.ecclix_county_list)

        if not username or not password:
            logger.warning("[ecclix] No credentials in Doppler; skipping batch")
            return []

        if not counties:
            counties = list(ECCLIX_URLS.keys())

        # Addresses to look up (populated by the lead queue)
        addresses = params.get("addresses", [])
        if not addresses:
            logger.info("[ecclix] No addresses provided for batch lookup")
            return []

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for county in counties:
                portal_url = ECCLIX_URLS.get(county.lower())
                if not portal_url:
                    logger.warning("[ecclix] Unknown county: %s", county)
                    continue

                try:
                    # Login to this county's eCCLIX portal
                    await self._login(page, portal_url, username, password)

                    # Batch lookup each address
                    for addr in addresses:
                        try:
                            batch = await self._search_records(page, portal_url, addr, county)
                            records.extend(batch)
                        except Exception as exc:
                            logger.warning("[ecclix] Search failed %s/%s: %s", county, addr, exc)
                        await human_delay(2.0, 4.0)

                except Exception as exc:
                    logger.error("[ecclix] Login/session failed for %s: %s", county, exc)

        logger.info("[ecclix] Batch complete: %d records across %d counties", len(records), len(counties))
        return records

    async def _login(self, page, portal_url: str, username: str, password: str) -> None:
        """Login to an eCCLIX county portal."""
        await safe_goto(page, portal_url)
        await human_delay()

        # Handle CAPTCHA on login page
        await detect_and_solve_captcha(page)

        user_input = await page.query_selector(
            "input#username, input[name='username'], input[name='user'], input[type='text']"
        )
        pass_input = await page.query_selector(
            "input#password, input[name='password'], input[type='password']"
        )

        if user_input and pass_input:
            await human_type(page, "input#username, input[name='username'], input[type='text']", username)
            await human_delay(0.5, 1.0)
            await human_type(page, "input#password, input[name='password'], input[type='password']", password)
            await human_delay(0.5, 1.0)

            login_btn = await page.query_selector(
                "button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign In')"
            )
            if login_btn:
                await login_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay()

        logger.info("[ecclix] Logged into %s", portal_url)

    async def _search_records(
        self, page, portal_url: str, address: str, county: str
    ) -> list[RawRecord]:
        """Search for deed/will/mortgage records by address."""
        records: list[RawRecord] = []

        # Navigate to search page
        search_url = f"{portal_url}/search"
        await safe_goto(page, search_url)
        await human_delay()

        search_input = await page.query_selector(
            "input#search, input[name='search'], input[name='address']"
        )
        if search_input:
            await search_input.fill(address)
            await human_delay(1.0, 2.0)

            submit = await page.query_selector("button[type='submit'], input[type='submit']")
            if submit:
                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay()

        # Extract result rows
        rows = await page.query_selector_all("tr.result-row, table.results tr:not(:first-child)")

        for row in rows[:20]:
            try:
                cells = await row.query_selector_all("td")
                cell_texts = []
                for cell in cells:
                    cell_texts.append((await cell.inner_text()).strip())

                if len(cell_texts) >= 3:
                    records.append(RawRecord(
                        source_key=self.source_key,
                        data={
                            "county": county,
                            "address": address,
                            "doc_type": cell_texts[0],  # DEED, WILL, MORTGAGE, etc.
                            "grantor": cell_texts[1] if len(cell_texts) > 1 else "",
                            "grantee": cell_texts[2] if len(cell_texts) > 2 else "",
                            "date": cell_texts[3] if len(cell_texts) > 3 else "",
                            "consideration": cell_texts[4] if len(cell_texts) > 4 else "",
                            "book_page": cell_texts[5] if len(cell_texts) > 5 else "",
                            "cells": cell_texts,
                        },
                    ))
            except Exception as exc:
                logger.debug("[ecclix] Row parse error: %s", exc)

        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        doc_type = (data.get("doc_type") or "").upper()

        # Classify by document type
        if "WILL" in doc_type or "PROBATE" in doc_type:
            lead_type = LeadType.PROBATE
        elif "MORTGAGE" in doc_type or "FORECLOS" in doc_type:
            lead_type = LeadType.FORECLOSURE
        elif "LIEN" in doc_type:
            lead_type = LeadType.TAX_LIEN
        else:
            lead_type = LeadType.ESTATE  # deeds, etc.

        county = data.get("county", "")
        consideration = data.get("consideration", "")
        estimated = None
        if consideration:
            try:
                estimated = float(consideration.replace(",", "").replace("$", "").strip())
            except ValueError:
                pass

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county.title()}",
            lead_type=lead_type,
            owner_name=data.get("grantor") or data.get("grantee"),
            property_address=data.get("address"),
            state="KY",
            case_id=data.get("book_page"),
            estimated_value=estimated,
            raw_payload=data,
        )
