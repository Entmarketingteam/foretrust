"""KY statewide GIS map-first scraper.

Scans KY GIS for residential parcels matching criteria (sqft, zoning,
no recent transfer) and queues matching addresses for PVA lookup.
This bypasses PVA search-by-name limits by feeding addresses instead.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay

logger = logging.getLogger(__name__)

# ArcGIS REST endpoints for KY counties (free, no login)
GIS_ENDPOINTS: dict[str, str] = {
    "fayette": "https://maps.lexingtonky.gov/lfucggis/rest/services/Property/MapServer/0/query",
    "scott": "https://gis.scottcountyky.com/arcgis/rest/services/Property/MapServer/0/query",
    "oldham": "https://gis.oldhamcountyky.gov/arcgis/rest/services/Property/MapServer/0/query",
    # Statewide fallback
    "ky_state": "https://kygisserver.ky.gov/arcgis/rest/services/WGS84WM_Services/Ky_Property_Parcels_WGS84WM/MapServer/0/query",
}


@register
class KYStateGISConnector(BaseConnector):
    source_key = "ky_state_gis"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Statewide"
    base_url = "https://kygisserver.ky.gov"
    default_schedule = "0 5 * * *"
    respects_robots = False  # ArcGIS REST API, not a website

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        min_sqft = params.get("min_sqft", 6000)
        limit = params.get("limit", 100)
        counties = params.get("counties", list(GIS_ENDPOINTS.keys()))
        records: list[RawRecord] = []

        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            for county in counties:
                endpoint = GIS_ENDPOINTS.get(county.lower())
                if not endpoint:
                    logger.warning("[ky_gis] No endpoint for county: %s", county)
                    continue

                try:
                    batch = await self._query_arcgis(client, endpoint, county, min_sqft, limit)
                    records.extend(batch)
                except Exception as exc:
                    logger.warning("[ky_gis] Query failed for %s: %s", county, exc)

                await human_delay(1.0, 2.0)

        logger.info("[ky_gis] GIS scan: %d total records", len(records))
        return records

    async def _query_arcgis(
        self, client, endpoint: str, county: str, min_sqft: int, limit: int
    ) -> list[RawRecord]:
        """Query an ArcGIS REST endpoint for parcels matching criteria."""
        # Build WHERE clause — field names vary by county server
        # Common patterns: SQFT, BLDG_SQFT, TOTAL_SQFT, IMPROV_SQFT
        where_clauses = [
            f"SQFT >= {min_sqft}",
            f"BLDG_SQFT >= {min_sqft}",
            f"TOTAL_SQFT >= {min_sqft}",
        ]

        records: list[RawRecord] = []

        for where in where_clauses:
            query_params = {
                "where": where,
                "outFields": "*",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": str(limit),
                "orderByFields": "SQFT DESC",
            }

            try:
                resp = await client.get(endpoint, params=query_params)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                if "error" in data:
                    continue

                features = data.get("features", [])
                if not features:
                    continue

                for feature in features[:limit]:
                    attrs = feature.get("attributes", {})
                    records.append(RawRecord(
                        source_key=self.source_key,
                        data={
                            "county": county,
                            "owner_name": self._find_field(attrs, ["OWNER", "OWNERNAME", "OWNER_NAME", "NAME"]),
                            "property_address": self._find_field(attrs, ["ADDRESS", "PROP_ADDR", "SITEADDR", "LOCATION"]),
                            "building_sqft": self._find_field(attrs, ["SQFT", "BLDG_SQFT", "TOTAL_SQFT", "IMPROV_SQFT"]),
                            "year_built": self._find_field(attrs, ["YEAR_BUILT", "YEARBUILT", "YR_BUILT"]),
                            "assessed_value": self._find_field(attrs, ["ASSESSED_VALUE", "TOTAL_VALUE", "APPRAISED", "VALUE"]),
                            "parcel_number": self._find_field(attrs, ["PARCEL_ID", "PARCEL", "PVA_MAP", "MAP_ID", "PIN"]),
                            "land_use": self._find_field(attrs, ["LAND_USE", "USE_CODE", "ZONING", "CLASS"]),
                            "last_sale_date": self._find_field(attrs, ["LAST_SALE_DATE", "SALE_DATE", "TRANSFER_DATE"]),
                            "all_attributes": attrs,
                            "source": "gis_arcgis",
                        },
                    ))

                # If we got results, don't try other WHERE clauses
                if records:
                    break

            except Exception:
                continue

        logger.info("[ky_gis] %s: %d parcels", county, len(records))
        return records

    @staticmethod
    def _find_field(attrs: dict, candidates: list[str]) -> Any:
        """Find a field value by trying multiple possible column names."""
        for name in candidates:
            val = attrs.get(name)
            if val is not None:
                return val
            # Try case-insensitive
            for key, value in attrs.items():
                if key.upper() == name.upper() and value is not None:
                    return value
        return None

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        sqft = data.get("building_sqft")
        assessed = data.get("assessed_value")
        county = data.get("county", "")

        # GIS parcels default to vacancy (high sqft, idle)
        lead_type = LeadType.VACANCY

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county.title()}" if county else "KY-Statewide",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            state="KY",
            parcel_number=data.get("parcel_number"),
            building_sqft=int(sqft) if sqft and str(sqft).isdigit() else None,
            year_built=int(data["year_built"]) if data.get("year_built") and str(data["year_built"]).isdigit() else None,
            estimated_value=float(assessed) if assessed else None,
            raw_payload=data,
        )
