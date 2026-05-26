"""eCCLIX Discovery Sweep (YOLO v8 - Advanced Boolean).

Executes specific distress-signal searches:
1. Party One Keywords: "ESTATE OF", "EXECUTOR", "ADMINISTRATOR", "ORCHARD TAX", "EAST COAST TAX", "LIEN WORKS"
2. Advanced Instrument Types: "LIS", "NOT", "AFF", "CERT", "CD"
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
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto, create_browser
from app.captcha import detect_and_solve_captcha
from app.config import settings
from app.storage.supabase_client import insert_leads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CENTRAL_PORTAL = "https://www.ecclix.com"

# HIGH-PRIORITY TYPES from user strategy
ADVANCED_TYPES = ["LIS", "NOT", "AFF", "CERT", "CD"]

# BOOLEAN PARTY ONE KEYWORDS
CORPORATE_TAX_BUYERS = ["ORCHARD TAX", "EAST COAST TAX", "LIEN WORKS"]
ESTATE_LIQUIDATION = ["ESTATE OF", "EXECUTOR", "ADMINISTRATOR"]

# SELECTORS
SEL_PARTY_ONE = "input#ctl00_Content_gbSearch_CalParty_uteParty1"
SEL_TYPE = "select#ctl00_Content_gbSearch_uceType"
SEL_START = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteFdate"
SEL_END = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteLdate"
SEL_SEARCH = "input#ctl00_Content_btnSearch"

@register
class ECCLIXAdvancedConnector(BaseConnector):
    source_key = "ecclix_advanced"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = CENTRAL_PORTAL
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        counties = params.get("counties", ["Bourbon", "Scott", "Woodford", "Franklin"])
        
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            try:
                await self._login(page, username, password)

                for county in counties:
                    try:
                        if not await self._select_county(page, county): continue

                        # 1. ESTATE LIQUIDATION (6 Months Back)
                        for kw in ESTATE_LIQUIDATION:
                            start = (date.today() - timedelta(days=180)).strftime("%m/%d/%Y")
                            batch = await self._search_by_party_one(page, county, kw, start)
                            records.extend(batch)
                            if batch: logger.info("[advanced] %s/%s: Found %d", county, kw, len(batch))
                            await human_delay(2.0, 3.0)

                        # 2. CORPORATE TAX BUYERS (12 Months Back)
                        for kw in CORPORATE_TAX_BUYERS:
                            start = (date.today() - timedelta(days=365)).strftime("%m/%d/%Y")
                            batch = await self._search_by_party_one(page, county, kw, start)
                            records.extend(batch)
                            if batch: logger.info("[advanced] %s/%s: Found %d", county, kw, len(batch))
                            await human_delay(2.0, 3.0)

                        # 3. ADVANCED INSTRUMENT TYPES (2026 Sweep)
                        for inst in ADVANCED_TYPES:
                            batch = await self._search_by_type(page, county, inst, "01/01/2026")
                            records.extend(batch)
                            if batch: logger.info("[advanced] %s/%s: Found %d", county, inst, len(batch))
                            await human_delay(2.0, 3.0)

                    except Exception as exc:
                        logger.error("[advanced] County %s failed: %s", county, exc)

            except Exception as exc:
                logger.error("[advanced] Fatal session error: %s", exc)

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
        await page.goto(f"{CENTRAL_PORTAL}/ecclix/usercounties.aspx")
        await page.wait_for_load_state("networkidle")
        links = await page.query_selector_all("a")
        for link in links:
            if county.upper() in (await link.inner_text()).upper():
                await link.click()
                await page.wait_for_load_state("networkidle")
                return True
        return False

    async def _search_by_party_one(self, page: Page, county: str, keyword: str, start: str) -> list[RawRecord]:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/instrinq.aspx")
        # Clear filters first
        await page.click("input[value='Reset'], #ctl00_Content_btnReset")
        await page.wait_for_load_state("networkidle")
        
        await page.fill(SEL_PARTY_ONE, keyword)
        await page.fill(SEL_START, start)
        await page.fill(SEL_END, date.today().strftime("%m/%d/%Y"))
        await page.click(SEL_SEARCH)
        await page.wait_for_load_state("networkidle")
        return await self._scrape_results(page, county)

    async def _search_by_type(self, page: Page, county: str, inst_type: str, start: str) -> list[RawRecord]:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/instrinq.aspx")
        await page.click("input[value='Reset'], #ctl00_Content_btnReset")
        await page.wait_for_load_state("networkidle")
        
        try:
            await page.select_option(SEL_TYPE, value=inst_type)
        except: return []
        
        await page.fill(SEL_START, start)
        await page.fill(SEL_END, date.today().strftime("%m/%d/%Y"))
        await page.click(SEL_SEARCH)
        await page.wait_for_load_state("networkidle")
        return await self._scrape_results(page, county)

    async def _scrape_results(self, page: Page, county: str) -> list[RawRecord]:
        records: list[RawRecord] = []
        rows = await page.query_selector_all("tr.result-row, #dgInstruments tr:not(:first-child), table.results tr:not(:first-child)")
        for row in rows[:300]:
            try:
                cells = await row.query_selector_all("td")
                txt = [ (await c.inner_text()).strip() for c in cells ]
                if len(txt) >= 3:
                    records.append(RawRecord(source_key=self.source_key, data={
                        "county": county, "doc_type": txt[0], "grantor": txt[1], "grantee": txt[2],
                        "date": txt[3] if len(txt) > 3 else "", "book_page": txt[5] if len(txt) > 5 else "",
                        "address": txt[6] if len(txt) > 6 else "Unknown",
                    }))
            except: continue
        return records

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        return Lead(
            source_key=self.source_key, vertical=Vertical.RESIDENTIAL, jurisdiction=f"KY-{d['county'].title()}",
            lead_type=LeadType.ESTATE, owner_name=d.get("grantor") or d.get("grantee"),
            property_address=d.get("address"), state="KY", case_id=d.get("book_page"), raw_payload=d,
        )

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", type=str)
    args = parser.parse_args()
    clist = args.counties.split(",") if args.counties else ["Bourbon", "Scott", "Woodford", "Franklin"]
    async with create_browser(headless=True) as browser:
        conn = ECCLIXAdvancedConnector()
        recs = await conn.fetch(browser, {"counties": clist})
        if recs:
            leads = [conn.parse(r) for r in recs]
            from app.storage.supabase_client import insert_leads
            await insert_leads(leads)
            logger.info("Persisted %d ADVANCED leads", len(leads))

if __name__ == "__main__":
    asyncio.run(main())
