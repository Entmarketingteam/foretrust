"""eCCLIX Discovery Sweep (YOLO v8 - Central Portal & Resilient).
"""

from __future__ import annotations

import logging
import argparse
import asyncio
import sys
from datetime import date
from typing import Any

from playwright.async_api import Browser, Page

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
DISCOVERY_INSTRUMENTS = ["WILL", "LP", "MTG", "DEED", "LC", "BOND", "WRAP"]

# EXACT SELECTORS from manual source inspection
SEL_TYPE = "select#ctl00_Content_gbSearch_uceType"
SEL_START = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteFdate"
SEL_END = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteLdate"
SEL_SEARCH = "input#ctl00_Content_btnSearch"

@register
class ECCLIXDiscoveryConnector(BaseConnector):
    source_key = "ecclix_discovery"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = CENTRAL_PORTAL
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        counties = params.get("counties", ["Bourbon", "Scott", "Woodford", "Franklin"])
        start_date = params.get("start_date", "01/01/2026")
        end_date = params.get("end_date", date.today().strftime("%m/%d/%Y"))

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            try:
                await self._login(page, username, password)

                for county in counties:
                    try:
                        if not await self._select_county(page, county): continue

                        for inst_type in DISCOVERY_INSTRUMENTS:
                            try:
                                batch = await self._search_by_date_range(page, county, inst_type, start_date, end_date)
                                records.extend(batch)
                                if batch: logger.info("[discovery] %s/%s: Found %d", county, inst_type, len(batch))
                            except Exception as exc:
                                logger.warning("[discovery] %s/%s failed: %s", county, inst_type, exc)
                            await human_delay(1.0, 2.0)
                    except Exception as exc:
                        logger.error("[discovery] County %s failed: %s", county, exc)

            except Exception as exc:
                logger.error("[discovery] Fatal session error: %s", exc)

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
        logger.info("[discovery] Selecting county: %s", county)
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

    async def _search_by_date_range(self, page: Page, county: str, inst_type: str, start: str, end: str) -> list[RawRecord]:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/instrinq.aspx")
        
        try:
            # eCCLIX uses ASP.NET dropdowns where 'label' is the visible text (e.g. WILL)
            await page.select_option(SEL_TYPE, label=inst_type)
            logger.info("[discovery] Selected %s for %s", inst_type, county)
        except:
            try:
                # Fallback to value search if label fails
                await page.select_option(SEL_TYPE, value=inst_type)
            except:
                logger.warning("[discovery] %s: Could not select %s", county, inst_type)
                return []
        
        await page.fill(SEL_START, start)
        await page.fill(SEL_END, end)
        await page.click(SEL_SEARCH)
        await page.wait_for_load_state("networkidle")
        return await self._scrape_results(page, county)

    async def _scrape_results(self, page: Page, county: str) -> list[RawRecord]:
        records: list[RawRecord] = []
        rows = await page.query_selector_all("tr.result-row, #dgInstruments tr:not(:first-child), table.results tr:not(:first-child)")
        for row in rows[:500]:
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
    parser.add_argument("--start-date", type=str, default="01/01/2026")
    parser.add_argument("--end-date", type=str)
    args = parser.parse_args()
    clist = args.counties.split(",") if args.counties else ["Bourbon", "Scott", "Woodford", "Franklin"]
    end_date = args.end_date or date.today().strftime("%m/%d/%Y")
    
    async with create_browser(headless=True) as browser:
        conn = ECCLIXDiscoveryConnector()
        recs = await conn.fetch(browser, {"counties": clist, "start_date": args.start_date, "end_date": end_date})
        if recs:
            leads = [conn.parse(r) for r in recs]
            from app.storage.supabase_client import insert_leads
            inserted = await insert_leads(leads)
            logger.info("Persisted %d DISCOVERY leads", inserted)

if __name__ == "__main__":
    asyncio.run(main())
