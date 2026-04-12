"""KY statewide GIS map-first scraper.

Scans KY GIS for residential parcels matching criteria (zoning class,
no recent transfer) and queues matching addresses for PVA lookup.
This bypasses PVA search-by-name limits by feeding addresses instead.

Verified working endpoints (tested 2025-04-11):
- fayette:  maps.lexingtonky.gov/lfucggis  layer 1 = "Parcel"
            fields: PVANUM, NAME (street name), ADDRESS, CLASS ('R'=residential), PVA_ACRE
- ky_state: kygisserver.ky.gov WGS84WM_Services/Ky_PVA_Webster_Parcels  layer 1 = "Webster Parcels"
            fields: PARCEL_ID, NAME (owner), ADDRESS1 (mailing), CLASS ('RESIDENTIAL'), ACRES, LOCATION (site addr)
- jefferson: gis.lojic.org LojicSolutions/OpenDataPVA  layer 1 = "Jefferson County KY Parcels"
             fields: PARCELID, PARCEL_TYPE, LRSN (geometry/ID only — no owner/address, used for parcel enumeration)

Note: None of these endpoints expose building sqft directly. The original
min_sqft filter has been replaced with CLASS-based residential filtering.
Building sqft (if needed) must be fetched from the county PVA lookup stage.
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

# ArcGIS REST endpoints for KY counties (free, no login required).
# Each entry maps county name → (query URL, residential WHERE clause, field mapping config)
GIS_ENDPOINTS: dict[str, dict] = {
    "fayette": {
        # Lexington-Fayette Urban County Government GIS
        # Layer 0 = Address Points, Layer 1 = Parcel
        "url": "https://maps.lexingtonky.gov/lfucggis/rest/services/property/MapServer/1/query",
        # CLASS = 'R' filters to residential parcels
        "where_residential": "CLASS = 'R'",
        # Field name mappings for this server
        "field_parcel_id": "PVANUM",
        "field_owner": None,          # NAME field is street name, not owner — fetch from PVA
        "field_address": "ADDRESS",
        "field_class": "CLASS",
        "field_acres": "PVA_ACRE",
    },
    "ky_state": {
        # KY Statewide GIS — Webster County parcels (one of the few counties
        # with parcel data published on kygisserver.ky.gov)
        "url": "https://kygisserver.ky.gov/arcgis/rest/services/WGS84WM_Services/Ky_PVA_Webster_Parcels_WGS84WM/MapServer/1/query",
        "where_residential": "CLASS = 'RESIDENTIAL'",
        "field_parcel_id": "PARCEL_ID",
        "field_owner": "NAME",         # Mailing address owner name
        "field_address": "LOCATION",   # LOCATION = site address; ADDRESS1 = mailing address
        "field_class": "CLASS",
        "field_acres": "ACRES",
    },
    "jefferson": {
        # Jefferson County (Louisville Metro) via LOJIC Open Data
        # NOTE: This layer only has parcel IDs + geometry — no owner/address.
        # It is included for parcel enumeration; PVA lookup stage must enrich records.
        "url": "https://gis.lojic.org/maps/rest/services/LojicSolutions/OpenDataPVA/MapServer/1/query",
        "where_residential": "PARCEL_TYPE = 0",  # Type 0 = standard parcels (vs ROW, condo, etc.)
        "field_parcel_id": "PARCELID",
        "field_owner": None,
        "field_address": None,
        "field_class": "PARCEL_TYPE",
        "field_acres": None,
    },
}

# Legacy flat URL dict kept for backwards compatibility with params["counties"] lookups
_LEGACY_URL_MAP: dict[str, str] = {k: v["url"] for k, v in GIS_ENDPOINTS.items()}


@register
class KYStateGISConnector(BaseConnector):
    source_key = "ky_state_gis"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Statewide"
    base_url = "https://kygisserver.ky.gov"
    default_schedule = "0 5 * * *"
    respects_robots = False  # ArcGIS REST API, not a website

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        limit = params.get("limit", 100)
        counties = params.get("counties", list(GIS_ENDPOINTS.keys()))
        records: list[RawRecord] = []

        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            for county in counties:
                cfg = GIS_ENDPOINTS.get(county.lower())
                if not cfg:
                    logger.warning("[ky_gis] No endpoint configured for county: %s", county)
                    continue

                try:
                    batch = await self._query_arcgis(client, cfg, county, limit)
                    records.extend(batch)
                except Exception as exc:
                    logger.warning("[ky_gis] Query failed for %s: %s", county, exc)

                await human_delay(1.0, 2.0)

        logger.info("[ky_gis] GIS scan: %d total records", len(records))
        return records

    async def _query_arcgis(
        self, client, cfg: dict, county: str, limit: int
    ) -> list[RawRecord]:
        """Query an ArcGIS REST endpoint for residential parcels."""
        endpoint = cfg["url"]
        where = cfg["where_residential"]

        query_params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": str(limit),
            # orderByFields omitted — field names vary per server and an unknown
            # field name causes the entire query to fail on ArcGIS 10.x
        }

        resp = await client.get(endpoint, params=query_params)
        if resp.status_code != 200:
            logger.warning("[ky_gis] HTTP %s from %s", resp.status_code, endpoint)
            return []

        data = resp.json()
        if "error" in data:
            logger.warning("[ky_gis] ArcGIS error for %s: %s", county, data["error"])
            return []

        features = data.get("features", [])
        if not features:
            logger.info("[ky_gis] %s: 0 features returned", county)
            return []

        records: list[RawRecord] = []
        for feature in features[:limit]:
            attrs = feature.get("attributes", {})

            owner = self._get_field(attrs, cfg.get("field_owner"))
            address = self._get_field(attrs, cfg.get("field_address"))
            parcel_id = self._get_field(attrs, cfg.get("field_parcel_id"))
            land_class = self._get_field(attrs, cfg.get("field_class"))
            acres = self._get_field(attrs, cfg.get("field_acres"))

            records.append(RawRecord(
                source_key=self.source_key,
                data={
                    "county": county,
                    "owner_name": owner,
                    "property_address": address,
                    "parcel_number": parcel_id,
                    "land_use": land_class,
                    "acres": acres,
                    # building_sqft not available in these GIS layers;
                    # must be fetched from county PVA lookup
                    "building_sqft": None,
                    "year_built": None,
                    "assessed_value": None,
                    "last_sale_date": None,
                    "all_attributes": attrs,
                    "source": "gis_arcgis",
                },
            ))

        logger.info("[ky_gis] %s: %d parcels returned", county, len(records))
        return records

    @staticmethod
    def _get_field(attrs: dict, field_name: str | None) -> Any:
        """Get a field value by exact name (case-insensitive fallback)."""
        if field_name is None:
            return None
        val = attrs.get(field_name)
        if val is not None:
            return val
        # Case-insensitive fallback
        upper = field_name.upper()
        for key, value in attrs.items():
            if key.upper() == upper and value is not None:
                return value
        return None

    @staticmethod
    def _find_field(attrs: dict, candidates: list[str]) -> Any:
        """Find a field value by trying multiple possible column names (legacy helper)."""
        for name in candidates:
            val = attrs.get(name)
            if val is not None:
                return val
            for key, value in attrs.items():
                if key.upper() == name.upper() and value is not None:
                    return value
        return None

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        acres = data.get("acres")
        assessed = data.get("assessed_value")
        county = data.get("county", "")

        # GIS parcels default to vacancy (large lot, idle residential)
        lead_type = LeadType.VACANCY

        # Convert acres to approximate sqft for the Lead model if available
        sqft = int(float(acres) * 43560) if acres else None

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county.title()}" if county else "KY-Statewide",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            state="KY",
            parcel_number=data.get("parcel_number"),
            building_sqft=sqft,
            year_built=None,
            estimated_value=float(assessed) if assessed else None,
            raw_payload=data,
        )
