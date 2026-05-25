"""eCCLIX wholesaler connector — discovery, download, import clerk instruments.

Modes (params.mode):
  wholesale (default on day pass) — date-range discovery per county, download PDFs,
    full grantor/grantee/legal/consideration → ft_leads + ft_clerk_documents
  address — enrich known lead addresses (legacy)
  name — search grantor/grantee from notice-derived names

Supports YOLO v6 resilient selectors and expanded discovery instruments.
"""

from __future__ import annotations

import logging
import argparse
import asyncio
import sys
import os
from datetime import date, timedelta
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.connectors.residential import ecclix_portal as portal
from app.connectors.residential.ecclix_county_config import (
    portal_bases_for,
    wholesale_instrument_codes,
)
from app.connectors.residential.ecclix_row_filters import apply_filters, hot_tier
from app.connectors.residential.ecclix_search_profiles import (
    DAY_PASS_SPRINT,
    DEEP_PORTAL_SEARCH,
    FULL_DAY_PASS_SPRINT,
    SIGNAL_INTEL_SEARCH,
    USABLE_EXTRACT,
    EcclixSearchProfile,
)
from app.pipeline.investment_scorer import best_strategy, score_from_lead_data
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto, create_browser
from app.captcha import detect_and_solve_captcha
from app.config import settings
from app.storage.clerk_documents import (
    extract_address_from_legal,
    insert_clerk_document,
    parse_consideration,
    parse_recorded_date,
    save_document_bytes,
)
from app.storage.supabase_client import insert_leads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CENTRAL_PORTAL = "https://www.ecclix.com"
DISTRESS_INSTRUMENTS = ["WILL", "LP", "DEED", "MTG", "SLIEN", "FLIEN", "AOD", "DJ", "JLIEN", "TLIEN", "LC", "BOND", "WRAP"]

DOC_TYPE_TO_LEAD: list[tuple[str, LeadType]] = [
    ("WILL", LeadType.PROBATE),
    ("PROBATE", LeadType.PROBATE),
    ("DEATH", LeadType.DEATH),
    ("MTG", LeadType.FORECLOSURE),
    ("MORTGAGE", LeadType.FORECLOSURE),
    ("DEED OF TRUST", LeadType.PRE_FORECLOSURE),
    ("LP", LeadType.PRE_FORECLOSURE),
    ("LIS PENDEN", LeadType.PRE_FORECLOSURE),
    ("FORECLOS", LeadType.FORECLOSURE),
    ("FLIEN", LeadType.TAX_LIEN),
    ("SLIEN", LeadType.TAX_LIEN),
    ("LIEN", LeadType.TAX_LIEN),
    ("LC", LeadType.ESTATE),
    ("BOND", LeadType.ESTATE),
    ("WRAP", LeadType.ESTATE),
]

# EXACT SELECTORS from manual source inspection
SEL_TYPE = "select#ctl00_Content_gbSearch_uceType"
SEL_START = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteFdate"
SEL_END = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteLdate"
SEL_SEARCH = "input#ctl00_Content_btnSearch"

@register
class ECCLIXBatchConnector(BaseConnector):
    source_key = "ecclix_batch"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = CENTRAL_PORTAL
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        if not username or not password:
            logger.warning("[ecclix] No credentials")
            return []

        mode = params.get("mode", "wholesale")
        counties = params.get("counties") or settings.ecclix_county_list or ["Bourbon", "Scott", "Woodford", "Franklin"]
        start_date = params.get("start_date", "01/01/2026")

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            try:
                await self._login(page, username, password)

                for county in counties:
                    try:
                        if not await self._select_county(page, county): continue

                        # 1. Search Instruments (Expanded Distress & Creative)
                        for inst_type in DISTRESS_INSTRUMENTS:
                            try:
                                batch = await self._search_by_date_range(page, county, inst_type, start_date)
                                records.extend(batch)
                                if batch: logger.info("[ecclix] %s/%s: Found %d", county, inst_type, len(batch))
                            except Exception as exc:
                                logger.warning("[ecclix] %s/%s failed: %s", county, inst_type, exc)
                            await human_delay(1.0, 2.0)

                        # 2. Search Taxes
                        if params.get("scrape_taxes", True):
                            try:
                                tax_records = await self._search_delinquent_taxes(page, county)
                                records.extend(tax_records)
                                if tax_records: logger.info("[ecclix] %s/TAX: Found %d", county, len(tax_records))
                            except Exception as exc:
                                logger.warning("[ecclix] %s/TAX failed: %s", county, exc)

                    except Exception as exc:
                        logger.error("[ecclix] County %s failed: %s", county, exc)

            except Exception as exc:
                logger.error("[ecclix] Fatal session error: %s", exc)

        logger.info("[ecclix] fetch complete: %d records (mode=%s)", len(records), mode)
        return records

    async def _login(self, page: Page, username: str, password: str) -> None:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/login.aspx")
        user_f = await page.query_selector("input#txtUsername")
        if user_f:
            await user_f.fill(username)
            await page.fill("input#txtPassword", password)
            await page.click("#btnLogin")
            await page.wait_for_load_state("networkidle")
            if "Force" in await page.content():
                btn = await page.query_selector("input[value*='Force']")
                if btn: await btn.click()
                await page.wait_for_load_state("networkidle")

    async def _select_county(self, page: Page, county: str) -> bool:
        logger.info("[ecclix] Selecting county: %s", county)
        await page.goto(f"{CENTRAL_PORTAL}/ecclix/usercounties.aspx")
        await page.wait_for_load_state("networkidle")
        
        links = await page.query_selector_all("a")
        for link in links:
            text = (await link.inner_text()).upper()
            if county.upper() in text:
                await link.click()
                await page.wait_for_load_state("networkidle")
                return True
        return False

    async def _search_by_date_range(self, page: Page, county: str, inst_type: str, start: str) -> list[RawRecord]:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/instrinq.aspx")
        try:
            await page.select_option(SEL_TYPE, value=inst_type)
        except:
            return []
        
        await page.fill(SEL_START, start)
        await page.fill(SEL_END, date.today().strftime("%m/%d/%Y"))
        await page.click(SEL_SEARCH)
        await page.wait_for_load_state("networkidle")
        return await self._scrape_results(page, county)

    async def _search_delinquent_taxes(self, page: Page, county: str) -> list[RawRecord]:
        await safe_goto(page, f"{CENTRAL_PORTAL}/Public/DTAX/Bills/Search")
        await page.click("input#Search, input[value='Search'], button:has-text('Search')")
        await page.wait_for_load_state("networkidle")
        return await self._scrape_results(page, county)

    async def _scrape_results(self, page: Page, county: str) -> list[RawRecord]:
        records: list[RawRecord] = []
        rows = await page.query_selector_all("tr.result-row, table.results tr:not(:first-child), #dgInstruments tr:not(:first-child), table[id*='GridView'] tr:not(:first-child)")
        for row in rows[:300]:
            try:
                cells = await row.query_selector_all("td")
                texts = [ (await c.inner_text()).strip() for c in cells ]
                if len(texts) >= 3:
                    records.append(RawRecord(source_key=self.source_key, data={
                        "county": county, "doc_type": texts[0], "grantor": texts[1], "grantee": texts[2],
                        "date": texts[3] if len(texts) > 3 else "", "book_page": texts[5] if len(texts) > 5 else "",
                        "address": texts[6] if len(texts) > 6 else "Unknown",
                    }))
            except: continue
        return records

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        dt = (d.get("doc_type") or "").upper()
        lt = LeadType.ESTATE
        for needle, lead_type in DOC_TYPE_TO_LEAD:
            if needle in dt:
                lt = lead_type
                break
        
        if any(x in dt for x in ["MORTGAGE", "FORECLOS", "LP", "DJ", "PENDENS"]): lt = LeadType.FORECLOSURE
        elif any(x in dt for x in ["LIEN", "TAX"]): lt = LeadType.TAX_LIEN

        return Lead(
            source_key=self.source_key, vertical=Vertical.RESIDENTIAL, jurisdiction=f"KY-{d['county'].title()}",
            lead_type=lt, owner_name=d.get("grantor") or d.get("grantee"), property_address=d.get("address"),
            state="KY", case_id=d.get("book_page"), raw_payload=d,
        )

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", type=str)
    parser.add_argument("--start-date", type=str, default="01/01/2026")
    args = parser.parse_args()
    clist = args.counties.split(",") if args.counties else ["Bourbon", "Scott", "Woodford", "Franklin"]
    
    async with create_browser(headless=True) as browser:
        conn = ECCLIXBatchConnector()
        recs = await conn.fetch(browser, {"counties": clist, "start_date": args.start_date, "scrape_taxes": True})
        leads = [conn.parse(r) for r in recs]
        if leads:
            from app.storage.supabase_client import insert_leads
            inserted = await insert_leads(leads)
            logger.info("Persisted %d leads", inserted)

if __name__ == "__main__":
    asyncio.run(main())
