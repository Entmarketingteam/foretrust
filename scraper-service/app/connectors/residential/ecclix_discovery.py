"""eCCLIX Discovery Sweep (YOLO v7 - Hybrid Portals).
"""

from __future__ import annotations

import logging
import argparse
import asyncio
import sys
import os
from datetime import date
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

# SUBDOMAINS from screenshots and research
COUNTY_PORTALS = {
    "bourbon": "https://bourbonky.ecclix.com",
    "scott": "https://scottky.ecclix.com",
    "woodford": "https://woodfordky.ecclix.com",
    "franklin": "https://franklinky.ecclix.com"
}

DISCOVERY_INSTRUMENTS = ["WILL", "LP", "MTG", "DEED", "LC", "BOND", "WRAP"]

@register
class ECCLIXDiscoveryConnector(BaseConnector):
    source_key = "ecclix_discovery"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://www.ecclix.com"
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        counties = params.get("counties", ["Bourbon", "Scott", "Woodford", "Franklin"])
        start_date = params.get("start_date", "01/01/2026")

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            
            for county in counties:
                try:
                    c_key = county.lower()
                    portal = COUNTY_PORTALS.get(c_key, f"https://{c_key}ky.ecclix.com")
                    
                    logger.info("[discovery] Attacking %s via %s", county, portal)
                    await safe_goto(page, f"{portal}/ecclix/login.aspx")
                    
                    if await page.query_selector("input#txtUsername"):
                        await page.fill("input#txtUsername", username)
                        await page.fill("input#txtPassword", password)
                        await page.click("#btnLogin")
                        await page.wait_for_load_state("networkidle")
                        if "Force" in await page.content():
                            btn = await page.query_selector("input[value*='Force']")
                            if btn: await btn.click()
                            await page.wait_for_load_state("networkidle")

                    # Broad Sweep
                    for inst in DISCOVERY_INSTRUMENTS:
                        try:
                            await safe_goto(page, f"{portal}/ecclix/instrinq.aspx")
                            # Flexible selectors
                            sel = "select[name*='uceType'], select#Type, select#ctl00_Content_gbSearch_uceType"
                            dropdown = await page.wait_for_selector(sel, timeout=5000)
                            if dropdown:
                                await page.select_option(sel, label=inst)
                                await page.fill("input[name*='BeginningDate'], input#ctl00_Content_gbSearch_calFields_betweenDates_uteFdate", start_date)
                                await page.fill("input[name*='EndingDate'], input#ctl00_Content_gbSearch_calFields_betweenDates_uteLdate", date.today().strftime("%m/%d/%Y"))
                                await page.click("input#Search, #ctl00_Content_btnSearch")
                                await page.wait_for_load_state("networkidle")
                                
                                batch = await self._scrape_results(page, county)
                                records.extend(batch)
                                if batch: logger.info("[discovery] %s/%s: Found %d", county, inst, len(batch))
                        except Exception as e:
                            logger.warning("[discovery] %s/%s failed: %s", county, inst, e)
                except Exception as e:
                    logger.error("[discovery] County %s fatal: %s", county, e)

        return records

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
    args = parser.parse_args()
    clist = args.counties.split(",") if args.counties else ["Bourbon", "Scott", "Woodford", "Franklin"]
    async with create_browser(headless=True) as browser:
        conn = ECCLIXDiscoveryConnector()
        recs = await conn.fetch(browser, {"counties": clist, "start_date": args.start_date})
        if recs:
            leads = [conn.parse(r) for r in recs]
            from app.storage.supabase_client import insert_leads
            await insert_leads(leads)
            logger.info("Persisted %d DISCOVERY leads", len(leads))

if __name__ == "__main__":
    asyncio.run(main())
