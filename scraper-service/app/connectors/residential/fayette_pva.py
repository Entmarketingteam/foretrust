"""Fayette County PVA connector (Lexington, KY).

Uses fayettepva.com for full property record lookup and the Lexington GIS
ArcGIS REST API for parcel discovery.

Extracts via base class:
  - Owner name + mailing address (where to send the offer)
  - Building sqft, year built, bed/bath/stories
  - Assessed value (land + improvement breakdown)
  - Sales history (last 10 transfers with price + grantor/grantee)
  - Tax history (delinquency = high distress signal)
  - Homestead exemption (owner-occupied indicator)
  - Legal description + deed book/page
  - Land use code + zoning

Additionally uses the Lexington GIS ArcGIS REST API for discovery mode
(when no specific addresses are provided).
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector
from app.models import RawRecord
from app.browser import create_context, human_delay

logger = logging.getLogger(__name__)


@register
class FayettePVAConnector(BasePVAConnector):
    source_key = "fayette_pva"
    jurisdiction = "KY-Fayette"
    base_url = "https://fayettepva.com"
    county_name = "Fayette"
    city_name = "LEXINGTON"
    default_schedule = "0 */6 * * *"

    @property
    def search_path(self) -> str:
        return "/property-search"

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        search_addresses = params.get("addresses", [])
        search_names = params.get("names", [])
        min_sqft = params.get("min_sqft", 0)
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            if search_addresses:
                for addr in search_addresses[:limit]:
                    try:
                        record = await self._lookup(page, addr, search_by="address")
                        if record:
                            records.append(record)
                    except Exception as exc:
                        logger.warning("[fayette_pva] Address lookup failed for %s: %s", addr, exc)
                    await human_delay(2.0, 4.0)

            elif search_names:
                for name in search_names[:limit]:
                    try:
                        record = await self._lookup(page, name, search_by="name")
                        if record:
                            records.append(record)
                    except Exception as exc:
                        logger.warning("[fayette_pva] Name lookup failed for %s: %s", name, exc)
                    await human_delay(2.0, 4.0)

            else:
                # Discovery mode: query Lexington GIS ArcGIS REST API
                records = await self._scan_lexington_gis(min_sqft, limit)

        return records

    async def _scan_lexington_gis(self, min_sqft: int, limit: int) -> list[RawRecord]:
        """Query the Lexington GIS ArcGIS REST API for residential parcels.

        This returns parcel IDs + addresses for the PVA lookup pipeline.
        Field names vary — we try multiple field name patterns.
        """
        import httpx

        records: list[RawRecord] = []
        arcgis_url = (
            "https://maps.lexingtonky.gov/lfucggis/rest/services/property/MapServer/1/query"
        )

        where_clause = "CLASS = 'R'"
        if min_sqft > 0:
            where_clause += f" AND SQFT >= {min_sqft}"

        query_params = {
            "where": where_clause,
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": str(limit),
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(arcgis_url, params=query_params)
                if resp.status_code == 200:
                    data = resp.json()
                    for feature in data.get("features", [])[:limit]:
                        attrs = feature.get("attributes", {})
                        records.append(RawRecord(
                            source_key=self.source_key,
                            data={
                                "county": self.county_name,
                                "owner_name": attrs.get("OWNER") or attrs.get("NAME") or "",
                                "property_address": attrs.get("ADDRESS") or attrs.get("SITEADDR") or "",
                                "building_sqft": attrs.get("SQFT") or attrs.get("TOTAL_SQFT"),
                                "year_built": attrs.get("YEAR_BUILT") or attrs.get("YR_BUILT"),
                                "assessed_value": attrs.get("ASSESSED_VALUE") or attrs.get("TOTAL_VALUE"),
                                "parcel_number": attrs.get("PVANUM") or attrs.get("PARCEL_ID") or "",
                                "land_use": attrs.get("CLASS") or attrs.get("LAND_USE") or "",
                                "last_sale_date": attrs.get("LAST_SALE_DATE") or "",
                                "acres": attrs.get("PVA_ACRE") or attrs.get("ACRES"),
                                "source": "gis_arcgis",
                                "all_attributes": attrs,
                            },
                        ))
        except Exception as exc:
            logger.warning("[fayette_pva] Lexington GIS query failed: %s", exc)

        logger.info("[fayette_pva] GIS scan: %d parcels", len(records))
        return records
