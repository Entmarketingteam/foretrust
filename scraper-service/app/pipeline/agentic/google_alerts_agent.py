"""Google Alerts / Probate Sourcing Agent.

Scrapes Google Search for recent estate and obituary notices in target counties,
extracts names, and cross-references them against our property database.
"""

from __future__ import annotations
import os
import sys
import re
import urllib.parse
import logging
import asyncio
from datetime import date
from typing import Any

from playwright.async_api import Browser, Page

from app.browser import create_browser, safe_goto, human_delay
from app.models import Lead, LeadType, RawRecord, Vertical
from app.storage.supabase_client import insert_leads

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Search queries designed to find probate/estate setups early
PROBATE_QUERIES = [
    'site:legacy.com "Georgetown" "Scott County" KY "passed away"',
    'site:legacy.com "Paris" "Bourbon County" KY "passed away"',
    'site:legacy.com "Versailles" "Woodford County" KY "passed away"',
    'site:legacy.com "Frankfort" "Franklin County" KY "passed away"',
    '"estate of" "Scott County" "probate" KY',
    '"estate of" "Woodford County" "probate" KY',
    '"estate of" "Franklin County" "probate" KY',
    '"estate of" "Bourbon County" "probate" KY'
]

class GoogleAlertsProbateAgent:
    def __init__(self):
        self.source_key = "google_alerts_probate"

    async def run_sweep(self, browser: Browser) -> list[Lead]:
        page = await browser.new_page()
        all_leads = []

        for query in PROBATE_QUERIES:
            logger.info(f"[probate-agent] Running Google query: {query}")
            try:
                names = await self._scrape_google_query(page, query)
                logger.info(f"[probate-agent] Found {len(names)} potential names.")
                
                # Cross reference with our database
                for name in names:
                    lead = await self._cross_reference_pva(name)
                    if lead:
                        all_leads.append(lead)
            except Exception as e:
                logger.warning(f"[probate-agent] Query failed '{query}': {e}")
            await human_delay(3.0, 5.0)

        # Ingest to Supabase
        if all_leads:
            logger.info(f"[probate-agent] Persisting {len(all_leads)} matched probate leads...")
            await insert_leads(all_leads)
            
        return all_leads

    async def _scrape_google_query(self, page: Page, query: str) -> list[str]:
        """Query Google and parse search results for names."""
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}"
        
        await safe_goto(page, url)
        await page.wait_for_load_state("networkidle")

        title = await page.title()
        if "unusual traffic" in title.lower() or "captcha" in title.lower():
            logger.warning("[probate-agent] Blocked by Google WAF/Captcha.")
            return []

        snippets = await page.query_selector_all("div.VwiC3b, span.aCO63b") # Common Google snippet selectors
        names = []

        for snip in snippets:
            text = await snip.inner_text()
            # Simple NLP: Look for capitalized names near "passed away" or "estate of"
            match = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)\b.*passed away", text)
            if match:
                names.append(match.group(1))
                continue
                
            match_estate = re.search(r"Estate of ([A-Z][a-z]+ [A-Z][a-z]+)", text, re.IGNORECASE)
            if match_estate:
                names.append(match_estate.group(1))

        return list(set(names)) # Deduplicate

    async def _cross_reference_pva(self, name: str) -> Lead | None:
        """Cross reference extracted name with known property records (stubs for mock)."""
        # In a real run, this pings Supabase or PVAExpress to see if 'name' owns land
        # If match, returns Lead(lead_type=LeadType.PROBATE)
        logger.info(f"[probate-agent] Cross-referencing: '{name}'")
        return None

async def main():
    async with create_browser(headless=True) as browser:
        agent = GoogleAlertsProbateAgent()
        leads = await agent.run_sweep(browser)
        print(f"\n[probate-agent] Sweep Complete. Matched leads: {len(leads)}")

if __name__ == "__main__":
    asyncio.run(main())
