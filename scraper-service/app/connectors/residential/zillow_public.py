"""Zillow public records fallback connector.

Cross-references property addresses against Zillow's public records tab
to detect pre_foreclosure flags and estate/death signals.
Only triggered manually as an enrichment step per lead.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto

logger = logging.getLogger(__name__)


@register
class ZillowPublicConnector(BaseConnector):
    source_key = "zillow_public"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://www.zillow.com"
    default_schedule = ""  # manually triggered only
    respects_robots = True

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        addresses = params.get("addresses", [])
        limit = params.get("limit", 20)
        records: list[RawRecord] = []

        if not addresses:
            logger.info("[zillow] No addresses provided; zillow is enrichment-only")
            return records

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for addr in addresses[:limit]:
                try:
                    record = await self._lookup_address(page, addr)
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning("[zillow] Lookup failed for %s: %s", addr, exc)
                await human_delay(3.0, 6.0)

        return records

    async def _lookup_address(self, page, address: str) -> RawRecord | None:
        """Search Zillow for an address and extract public records data."""
        # Use Zillow search
        search_url = f"{self.base_url}/homes/{address.replace(' ', '-')}_rb/"
        await safe_goto(page, search_url)
        await human_delay(2.0, 4.0)

        data: dict[str, Any] = {
            "search_address": address,
            "source": "zillow_public",
        }

        # Check for pre-foreclosure badge
        preforeclosure = await page.query_selector(
            "[data-test='pre-foreclosure'], .pre-foreclosure-badge, "
            ":text('Pre-Foreclosure'), :text('pre-foreclosure')"
        )
        if preforeclosure:
            data["pre_foreclosure"] = True

        # Check for "estate sale" or death signals in listing description
        description_el = await page.query_selector(
            "[data-test='description'], .ds-overview, .listing-description"
        )
        if description_el:
            desc_text = (await description_el.inner_text()).strip().upper()
            data["description_excerpt"] = desc_text[:500]
            if any(kw in desc_text for kw in ["ESTATE SALE", "ESTATE OF", "DECEASED", "PROBATE"]):
                data["estate_signal"] = True

        # Extract price / zestimate
        price_el = await page.query_selector(
            "[data-test='property-card-price'], .ds-summary-row .ds-value, .price"
        )
        if price_el:
            price_text = (await price_el.inner_text()).strip()
            data["listed_price"] = price_text

        # Extract basic property facts
        facts = await page.query_selector_all(
            "[data-test='bed-bath-item'], .ds-bed-bath-living-area span, .fact-value"
        )
        fact_texts = []
        for f in facts:
            fact_texts.append((await f.inner_text()).strip())
        if fact_texts:
            data["property_facts"] = fact_texts

        # Public records tab
        public_records_link = await page.query_selector(
            "a:has-text('Public Records'), a:has-text('Tax History')"
        )
        if public_records_link:
            await public_records_link.click()
            await human_delay(2.0, 3.0)

            tax_rows = await page.query_selector_all(
                ".tax-history-row, table.tax-history tr"
            )
            tax_data = []
            for row in tax_rows[:5]:
                text = (await row.inner_text()).strip()
                tax_data.append(text)
            if tax_data:
                data["tax_history"] = tax_data

        if not data.get("pre_foreclosure") and not data.get("estate_signal"):
            # No distress signals found
            return None

        return RawRecord(source_key=self.source_key, data=data)

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data

        # Classify lead type
        if data.get("pre_foreclosure"):
            lead_type = LeadType.PRE_FORECLOSURE
        elif data.get("estate_signal"):
            lead_type = LeadType.DEATH
        else:
            lead_type = LeadType.VACANCY

        # Parse price
        estimated = None
        price_str = data.get("listed_price", "")
        if price_str:
            try:
                clean = price_str.replace("$", "").replace(",", "").strip()
                if clean and clean[0].isdigit():
                    estimated = float(clean)
            except ValueError:
                pass

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction="KY-Multi",
            lead_type=lead_type,
            property_address=data.get("search_address"),
            state="KY",
            estimated_value=estimated,
            raw_payload=data,
        )
