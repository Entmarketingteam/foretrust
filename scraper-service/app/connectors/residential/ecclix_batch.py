\"\"\"eCCLIX multi-county batch runner.

Batch-scrapes deed, will, and mortgage records across eCCLIX counties
(Scott, Clark, Madison, Bourbon, Woodford, Franklin) using a single day-pass.

Supports:
1. Instrument Search: WILL, DEED, SLIEN, FLIEN, LP, AOD, AOC, DJ.
2. Delinquent Tax Search: Direct extraction from the eCCLIX tax portal.

Triggering: on-demand via POST /api/foretrust/leads/scrape {source_key: \"ecclix_batch\"}.
\"\"\"

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from playwright.async_api import Browser, Page

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto
from app.captcha import detect_and_solve_captcha
from app.config import settings

logger = logging.getLogger(__name__)

ECCLIX_URLS: dict[str, str] = {
    \"scott\": \"https://scottky.ecclix.com\",
    \"clark\": \"https://clarkky.ecclix.com\",
    \"madison\": \"https://madisonky.ecclix.com\",
    \"bourbon\": \"https://bourbonky.ecclix.com\",
    \"woodford\": \"https://woodfordky.ecclix.com\",
    \"franklin\": \"https://franklinky.ecclix.com\",
}

DISTRESS_INSTRUMENTS = [\"WILL\", \"DEED\", \"SLIEN\", \"FLIEN\", \"LP\", \"AOD\", \"AOC\", \"DJ\"]


@register
class ECCLIXBatchConnector(BaseConnector):
    source_key = \"ecclix_batch\"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = \"KY-Multi\"
    base_url = \"https://scottky.ecclix.com\"
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        counties = params.get(\"counties\", settings.ecclix_county_list) or list(ECCLIX_URLS.keys())
        
        start_date = params.get(\"start_date\", \"01/01/2026\")
        end_date = params.get(\"end_date\", date.today().strftime(\"%m/%d/%Y\"))
        instrument_types = params.get(\"instrument_types\", DISTRESS_INSTRUMENTS)

        if not username or not password:
            logger.warning(\"[ecclix] No credentials in Doppler; skipping\")
            return []

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for county in counties:
                portal_url = ECCLIX_URLS.get(county.lower())
                if not portal_url: continue

                try:
                    await self._login(page, portal_url, username, password)

                    # 1. Search Instruments (Estates, Probate, Liens, Divorces)
                    for inst_type in instrument_types:
                        try:
                            batch = await self._search_by_date_range(
                                page, portal_url, county, inst_type, start_date, end_date
                            )
                            records.extend(batch)
                        except Exception as exc:
                            logger.warning(\"[ecclix] Instrument search failed %s/%s: %s\", county, inst_type, exc)
                        await human_delay(1.0, 2.0)

                    # 2. Search Delinquent Taxes
                    if params.get(\"scrape_taxes\", True):
                        try:
                            tax_records = await self._search_delinquent_taxes(page, portal_url, county)
                            records.extend(tax_records)
                        except Exception as exc:
                            logger.warning(\"[ecclix] Tax search failed %s: %s\", county, exc)

                except Exception as exc:
                    logger.error(\"[ecclix] Session failed for %s: %s\", county, exc)

        return records

    async def _login(self, page: Page, portal_url: str, username: str, password: str) -> None:
        await safe_goto(page, f\"{portal_url}/ecclix/instrinq.aspx\")
        if await page.query_selector(\"input#PartyOne\"): return

        await detect_and_solve_captcha(page)
        if await page.query_selector(\"input#username\"):
            await human_type(page, \"input#username\", username)
            await human_type(page, \"input#password\", password)
            await page.click(\"button[type='submit'], input[type='submit']\")
            await page.wait_for_load_state(\"networkidle\")

    async def _search_by_date_range(self, page: Page, portal_url: str, county: str, inst_type: str, start: str, end: str) -> list[RawRecord]:
        await safe_goto(page, f\"{portal_url}/ecclix/instrinq.aspx\")
        try:
            await page.select_option(\"select#Type\", label=inst_type)
        except:
            await page.select_option(\"select#Type\", value=inst_type)
        
        await page.fill(\"input#BeginningDate\", start)
        await page.fill(\"input#EndingDate\", end)
        await page.click(\"input#Search\")
        await page.wait_for_load_state(\"networkidle\")
        return await self._scrape_results(page, county)

    async def _search_delinquent_taxes(self, page: Page, portal_url: str, county: str) -> list[RawRecord]:
        # Navigate to the Delinquent Tax tab
        await page.click(\"a:has-text('Delinquent Tax')\")
        await page.wait_for_load_state(\"networkidle\")
        
        # Click 'Search' button without params to get recent/all
        search_btn = await page.query_selector(\"input#Search, button:has-text('Search')\")
        if search_btn:
            await search_btn.click()
            await page.wait_for_load_state(\"networkidle\")
            
        return await self._scrape_results(page, county)

    async def _scrape_results(self, page: Page, county: str) -> list[RawRecord]:
        records: list[RawRecord] = []
        rows = await page.query_selector_all(\"tr.result-row, table.results tr:not(:first-child)\")
        for row in rows[:50]:
            try:
                cells = await row.query_selector_all(\"td\")
                texts = [ (await c.inner_text()).strip() for c in cells ]
                if len(texts) >= 3:
                    records.append(RawRecord(source_key=self.source_key, data={
                        \"county\": county, \"doc_type\": texts[0], \"grantor\": texts[1], \"grantee\": texts[2],
                        \"date\": texts[3] if len(texts) > 3 else \"\", \"consideration\": texts[4] if len(texts) > 4 else \"\",
                        \"book_page\": texts[5] if len(texts) > 5 else \"\", \"address\": texts[6] if len(texts) > 6 else \"\",
                        \"cells\": texts,
                    }))
            except: continue
        return records

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        dt = (d.get(\"doc_type\") or \"\").upper()
        lt = LeadType.ESTATE
        if any(x in dt for x in [\"WILL\", \"PROBATE\", \"AOD\", \"AOC\"]): lt = LeadType.PROBATE
        elif any(x in dt for x in [\"MORTGAGE\", \"FORECLOS\", \"LP\", \"DJ\"]): lt = LeadType.FORECLOSURE
        elif any(x in dt for x in [\"LIEN\", \"TAX\"]): lt = LeadType.TAX_LIEN

        return Lead(
            source_key=self.source_key, vertical=Vertical.RESIDENTIAL, jurisdiction=f\"KY-{d['county'].title()}\",
            lead_type=lt, owner_name=d.get(\"grantor\") or d.get(\"grantee\"), property_address=d.get(\"address\"),
            state=\"KY\", case_id=d.get(\"book_page\"), raw_payload=d,
        )
