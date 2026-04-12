"""Jefferson County (Louisville Metro) PVA connector.

Jefferson County / Louisville Metro is the largest KY market.
The PVA property search is at property.louisvilleky.gov.
Also leverages the LOJIC ArcGIS REST API for parcel enumeration.

Louisville Metro property search portal:
  https://www.jeffersonpva.ky.gov/property-search/
  (also accessible via https://property.louisvilleky.gov)

Additional LOJIC ArcGIS endpoint for parcel data is already in ky_state_gis.py.
This connector handles the detailed PVA property record lookup.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector
from app.models import RawRecord
from app.browser import create_context, human_delay, safe_goto

logger = logging.getLogger(__name__)


@register
class JeffersonPVAConnector(BasePVAConnector):
    source_key = "jefferson_pva"
    jurisdiction = "KY-Jefferson"
    base_url = "https://www.jeffersonpva.ky.gov"
    county_name = "Jefferson"
    city_name = "LOUISVILLE"
    default_schedule = "0 8 * * *"

    @property
    def search_path(self) -> str:
        return "/property-search/"

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        """Jefferson County has a higher-volume market — batch mode supported."""
        search_addresses = params.get("addresses", [])
        search_names = params.get("names", [])
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            # Jefferson PVA uses a specific LOJIC-style search interface
            # Try address lookup first, fall back to base class behavior
            for addr in search_addresses[:limit]:
                try:
                    record = await self._jefferson_address_lookup(page, addr)
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning("[jefferson_pva] Lookup failed for %s: %s", addr, exc)
                await human_delay(2.0, 4.0)

            for name in search_names[:limit]:
                try:
                    record = await self._lookup(page, name, search_by="name")
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning("[jefferson_pva] Name lookup failed for %s: %s", name, exc)
                await human_delay(2.0, 4.0)

        return records

    async def _jefferson_address_lookup(self, page, address: str) -> RawRecord | None:
        """Jefferson County specific address lookup flow."""
        search_url = f"{self.base_url}{self.search_path}"
        await safe_goto(page, search_url)
        await human_delay(1.5, 2.5)

        # Jefferson PVA search field
        input_sel = (
            "input#address-search, input#search-input, "
            "input[name='address'], input[placeholder*='address' i], "
            "input[placeholder*='property' i], input[type='text']"
        )
        search_input = await page.query_selector(input_sel)
        if not search_input:
            # Fall back to base class method
            return await self._lookup(page, address, search_by="address")

        await search_input.fill(address)
        await human_delay(0.8, 1.5)

        submit = await page.query_selector(
            "button[type='submit'], input[type='submit'], button:has-text('Search')"
        )
        if submit:
            await submit.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1.5, 2.5)

        # Click first result
        result_link = await page.query_selector(
            ".search-result a, .property-result a, table tr:not(:first-child) a"
        )
        if result_link:
            await result_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1.5, 2.5)

        return await self._extract_full_record(page, address)
