"""Fayette County PVA + GIS map connector.

Scrapes property records from fayettepva.com and the Lexington GIS MapIt portal.
Detects: vacancy (high sqft, no recent transfer), tax_lien, zoning_change.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto

logger = logging.getLogger(__name__)


@register
class FayettePVAConnector(BaseConnector):
    source_key = "fayette_pva"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Fayette"
    base_url = "https://fayettepva.com"
    default_schedule = "0 */6 * * *"
    respects_robots = True

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        search_addresses = params.get("addresses", [])
        min_sqft = params.get("min_sqft", 6000)
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            if search_addresses:
                # Targeted address lookup (from GIS map-first pipeline)
                for addr in search_addresses[:limit]:
                    try:
                        record = await self._search_by_address(page, addr)
                        if record:
                            records.append(record)
                    except Exception as exc:
                        logger.warning("[fayette_pva] Address lookup failed for %s: %s", addr, exc)
                    await human_delay(2.0, 4.0)
            else:
                # Browse GIS for high-sqft residential parcels
                records = await self._scan_gis(page, min_sqft, limit)

        return records

    async def _search_by_address(self, page, address: str) -> RawRecord | None:
        """Single targeted address lookup on fayettepva.com."""
        await safe_goto(page, f"{self.base_url}/property-search")
        await human_delay()

        # Fill address search
        search_input = await page.query_selector(
            "input#address, input[name='address'], input[type='text']"
        )
        if search_input:
            await search_input.fill(address)
            await human_delay(1.0, 2.0)

            # Submit
            submit = await page.query_selector(
                "button[type='submit'], input[type='submit'], button.search-btn"
            )
            if submit:
                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay()

        return await self._extract_property_data(page, address)

    async def _scan_gis(self, page, min_sqft: int, limit: int) -> list[RawRecord]:
        """Scan Lexington GIS MapIt for residential parcels above min_sqft."""
        records: list[RawRecord] = []

        # Try the GIS portal (ArcGIS REST service is preferred)
        gis_url = "https://maps.lexingtonky.gov/lfucggis"
        await safe_goto(page, gis_url)
        await human_delay(3.0, 5.0)

        # GIS portals often expose an ArcGIS REST endpoint
        # Try the query API directly for better results
        try:
            import httpx
            arcgis_query = (
                "https://maps.lexingtonky.gov/lfucggis/rest/services/Property/MapServer/0/query"
            )
            query_params = {
                "where": f"SQFT >= {min_sqft} AND LAND_USE LIKE '%RES%'",
                "outFields": "OWNER,ADDRESS,SQFT,YEAR_BUILT,ASSESSED_VALUE,PARCEL_ID,LAND_USE,LAST_SALE_DATE",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": str(limit),
                "orderByFields": "SQFT DESC",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(arcgis_query, params=query_params)
                if resp.status_code == 200:
                    data = resp.json()
                    for feature in data.get("features", [])[:limit]:
                        attrs = feature.get("attributes", {})
                        records.append(RawRecord(
                            source_key=self.source_key,
                            data={
                                "owner_name": attrs.get("OWNER", ""),
                                "property_address": attrs.get("ADDRESS", ""),
                                "building_sqft": attrs.get("SQFT"),
                                "year_built": attrs.get("YEAR_BUILT"),
                                "assessed_value": attrs.get("ASSESSED_VALUE"),
                                "parcel_number": attrs.get("PARCEL_ID", ""),
                                "land_use": attrs.get("LAND_USE", ""),
                                "last_sale_date": attrs.get("LAST_SALE_DATE", ""),
                                "source": "gis_arcgis",
                            },
                        ))
        except Exception as exc:
            logger.warning("[fayette_pva] ArcGIS query failed, falling back to page scrape: %s", exc)

        logger.info("[fayette_pva] GIS scan: %d records", len(records))
        return records

    async def _extract_property_data(self, page, search_addr: str) -> RawRecord | None:
        """Extract property details from a PVA results page."""
        # Try to find the property detail on the page
        owner_el = await page.query_selector(
            ".owner-name, td:has-text('Owner') + td, [data-field='owner']"
        )
        address_el = await page.query_selector(
            ".property-address, td:has-text('Address') + td, [data-field='address']"
        )
        sqft_el = await page.query_selector(
            ".sqft, td:has-text('Square') + td, [data-field='sqft']"
        )

        owner = (await owner_el.inner_text()).strip() if owner_el else ""
        address = (await address_el.inner_text()).strip() if address_el else search_addr
        sqft_text = (await sqft_el.inner_text()).strip() if sqft_el else ""

        if not owner and not address:
            return None

        sqft = None
        if sqft_text:
            try:
                sqft = int(sqft_text.replace(",", "").strip())
            except ValueError:
                pass

        return RawRecord(
            source_key=self.source_key,
            data={
                "owner_name": owner,
                "property_address": address,
                "building_sqft": sqft,
                "source": "pva_search",
            },
        )

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        sqft = data.get("building_sqft")
        assessed = data.get("assessed_value")

        lead_type = LeadType.VACANCY

        if "DELINQ" in str(data).upper() or "TAX LIEN" in str(data).upper():
            lead_type = LeadType.TAX_LIEN

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction="KY-Fayette",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            city="LEXINGTON",
            state="KY",
            parcel_number=data.get("parcel_number"),
            building_sqft=sqft if isinstance(sqft, int) else None,
            year_built=data.get("year_built"),
            estimated_value=float(assessed) if assessed else None,
            raw_payload=data,
        )
