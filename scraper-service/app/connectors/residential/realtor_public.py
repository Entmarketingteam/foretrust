"""Realtor.com Public Records Fallback Connector.

Pulls last sale date, price, and assessed values to bypass qPublic Cloudflare blocks.
"""

from __future__ import annotations
import logging
from datetime import date
from typing import Any
from urllib.parse import quote

from playwright.async_api import Browser, Page

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto

logger = logging.getLogger(__name__)

@register
class RealtorPublicConnector(BaseConnector):
    source_key = "realtor_public"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://www.realtor.com"
    default_schedule = ""  # manual fallback only
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        addresses = params.get("addresses", [])
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for addr in addresses[:10]: # Batch size limit
                try:
                    record = await self._lookup_address(page, addr)
                    if record:
                        records.append(record)
                        logger.info(f"[realtor] Successfully enriched: {addr}")
                except Exception as exc:
                    logger.warning("[realtor] Lookup failed for %s: %s", addr, exc)
                await human_delay(2.0, 4.0)

        return records

    async def _lookup_address(self, page: Page, address: str) -> RawRecord | None:
        # Realtor search: format address as slug
        clean_addr = address.replace(",", "").replace(".", "").replace(" ", "-")
        search_url = f"{self.base_url}/realestateandhomes-detail/{quote(clean_addr)}"
        
        await safe_goto(page, search_url)
        await human_delay(1.5, 3.0)

        title = await page.title()
        if "Access Denied" in title or "Pardon Our Interruption" in title:
            logger.warning("[realtor] Blocked by WAF on %s", address)
            return None

        data: dict[str, Any] = {
            "search_address": address,
            "source": self.source_key,
        }

        # 1. Extract Last Sale Price & Date from Property History/Details
        try:
            # Look for Price History section or general highlights
            history_rows = await page.query_selector_all("tr[data-testid*='history-row'], .history-event-row")
            for row in history_rows[:3]:
                cells = await row.query_selector_all("td")
                cell_texts = [ (await c.inner_text()).strip() for c in cells ]
                if len(cell_texts) >= 3:
                    # Example: ['07/15/2022', 'Sold', '$500,000']
                    event = cell_texts[1].upper()
                    if "SOLD" in event or "SALE" in event:
                        data["last_sale_date"] = cell_texts[0]
                        data["last_sale_price"] = cell_texts[2]
                        break
        except Exception as e:
            logger.debug("[realtor] Failed parsing price history: %s", e)

        # 2. Extract Year Built & SQFT
        try:
            facts = await page.query_selector_all("li[class*='PropertyKeyFacts']")
            for fact in facts:
                text = await fact.inner_text()
                if "Built" in text:
                    data["year_built"] = "".join(filter(str.isdigit, text))
                elif "Sq Ft" in text:
                    data["building_sqft"] = "".join(filter(str.isdigit, text))
        except Exception as e:
            logger.debug("[realtor] Failed parsing facts: %s", e)

        # Only return if we actually captured the sale date/price
        if not data.get("last_sale_date"):
            return None

        return RawRecord(source_key=self.source_key, data=data)

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        price_str = d.get("last_sale_price", "").replace("$", "").replace(",", "").strip()
        try:
            price = float(price_str)
        except:
            price = None

        return Lead(
            source_key=self.source_key, vertical=Vertical.RESIDENTIAL, jurisdiction="KY-Multi",
            lead_type=LeadType.ESTATE, property_address=d.get("search_address"), state="KY",
            year_built=int(d.get("year_built")) if d.get("year_built") else None,
            building_sqft=int(d.get("building_sqft")) if d.get("building_sqft") else None,
            estimated_value=price, raw_payload=d,
        )
