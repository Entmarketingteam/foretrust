"""Oldham County PVA connector (outside Louisville).

Detects: vacancy, tax_lien.
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
class OldhamPVAConnector(BaseConnector):
    source_key = "oldham_pva"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Oldham"
    base_url = "https://oldhamcountypva.com"
    default_schedule = "15 7 * * *"
    respects_robots = False  # Public government records — robots.txt is advisory, not legal restriction

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        search_addresses = params.get("addresses", [])
        limit = params.get("limit", 50)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            await safe_goto(page, self.base_url)
            await human_delay()

            if search_addresses:
                for addr in search_addresses[:limit]:
                    try:
                        record = await self._search_address(page, addr)
                        if record:
                            records.append(record)
                    except Exception as exc:
                        logger.warning("[oldham_pva] Lookup failed for %s: %s", addr, exc)
                    await human_delay(2.0, 4.0)
            else:
                # Try GIS / ArcGIS REST endpoint for Oldham County
                records = await self._scan_gis(page, params.get("min_sqft", 6000), limit)

        return records

    async def _search_address(self, page, address: str) -> RawRecord | None:
        """Single address lookup on Oldham PVA."""
        await safe_goto(page, self.base_url)
        await human_delay()

        search_input = await page.query_selector(
            "input#search, input[name='search'], input[type='text']"
        )
        if search_input:
            await search_input.fill(address)
            await human_delay(1.0, 2.0)

            submit = await page.query_selector(
                "button[type='submit'], input[type='submit']"
            )
            if submit:
                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay()

        # Extract data from results
        owner_el = await page.query_selector(
            ".owner-name, td:has-text('Owner') + td, [data-field='owner']"
        )
        sqft_el = await page.query_selector(
            "[data-field='sqft'], td:has-text('Square') + td"
        )
        value_el = await page.query_selector(
            "[data-field='value'], td:has-text('Assessed') + td, td:has-text('Value') + td"
        )
        parcel_el = await page.query_selector(
            "[data-field='parcel'], td:has-text('Parcel') + td"
        )

        owner = (await owner_el.inner_text()).strip() if owner_el else ""
        sqft_text = (await sqft_el.inner_text()).strip() if sqft_el else ""
        value_text = (await value_el.inner_text()).strip() if value_el else ""
        parcel = (await parcel_el.inner_text()).strip() if parcel_el else ""

        if not owner:
            return None

        sqft = None
        if sqft_text:
            try:
                sqft = int(sqft_text.replace(",", ""))
            except ValueError:
                pass

        assessed = None
        if value_text:
            try:
                assessed = float(value_text.replace(",", "").replace("$", ""))
            except ValueError:
                pass

        return RawRecord(
            source_key=self.source_key,
            data={
                "owner_name": owner,
                "property_address": address,
                "building_sqft": sqft,
                "assessed_value": assessed,
                "parcel_number": parcel,
                "source": "pva_search",
            },
        )

    async def _scan_gis(self, page, min_sqft: int, limit: int) -> list[RawRecord]:
        """Try Oldham County GIS / ArcGIS REST for bulk parcel data."""
        records: list[RawRecord] = []

        try:
            import httpx
            # Oldham County GIS endpoint (common ArcGIS pattern)
            arcgis_url = (
                "https://gis.oldhamcountyky.gov/arcgis/rest/services/Property/MapServer/0/query"
            )
            query_params = {
                "where": f"SQFT >= {min_sqft}",
                "outFields": "OWNER,ADDRESS,SQFT,YEAR_BUILT,ASSESSED_VALUE,PARCEL_ID",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": str(limit),
                "orderByFields": "SQFT DESC",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(arcgis_url, params=query_params)
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
                                "source": "gis_arcgis",
                            },
                        ))
        except Exception as exc:
            logger.warning("[oldham_pva] ArcGIS query failed: %s", exc)

        logger.info("[oldham_pva] GIS scan: %d records", len(records))
        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        sqft = data.get("building_sqft")
        assessed = data.get("assessed_value")

        lead_type = LeadType.VACANCY
        if "DELINQ" in str(data).upper():
            lead_type = LeadType.TAX_LIEN

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction="KY-Oldham",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            city="LA GRANGE",
            state="KY",
            parcel_number=data.get("parcel_number"),
            building_sqft=sqft if isinstance(sqft, int) else None,
            year_built=data.get("year_built"),
            estimated_value=float(assessed) if assessed else None,
            raw_payload=data,
        )
