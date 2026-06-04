"""Woodford County PVA (Versailles) — High-speed, Cloudflare-bypassing GIS connector."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from playwright.async_api import Browser

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector
from app.models import RawRecord
from app.pipeline.property_address import normalize_property_address

logger = logging.getLogger(__name__)


def _woodford_situs(v: str | None) -> str | None:
    """Woodford 'Location' is the situs as 'STREET NAME <number>' (reversed).
    Move the trailing number to the front. No trailing number => no street
    address on file (unaddressed/vacant parcel) => skip."""
    if not v:
        return None
    v = v.strip()
    m = re.search(r"\s+(\d+[A-Za-z]?)$", v)
    if not m:
        return None
    return f"{m.group(1)} {v[:m.start()].strip()}"


@register
class WoodfordPVAConnector(BasePVAConnector):
    source_key = "woodford_pva"
    jurisdiction = "KY-Woodford"
    county_name = "Woodford"
    city_name = "VERSAILLES"
    default_schedule = "0 8 * * *"

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        """Fetch Woodford records using high-speed Esri ArcGIS REST queries to bypass Cloudflare."""
        search_addresses = params.get("addresses", [])
        search_names = params.get("names", [])
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        logger.info("[%s] Bypassing qPublic. Querying Esri REST for %d addresses and %d names...",
                    self.source_key, len(search_addresses), len(search_names))

        URL = "https://services9.arcgis.com/eE18Y8QhAVKzp7mP/arcgis/rest/services/Parcels/FeatureServer/0/query"

        async with httpx.AsyncClient(timeout=15) as client:
            # Address queries
            for addr in search_addresses[:limit]:
                # Extract number and street name
                norm_addr = normalize_property_address(addr)
                if not norm_addr:
                    continue
                parts = norm_addr.split()
                if not parts:
                    continue
                num = parts[0]
                street = " ".join(parts[1:]).upper()

                # Esri Location matches "STREET % <number>"
                where = f"Location LIKE '%{street}%{num}%'"
                params_gis = {
                    "where": where,
                    "outFields": "Name,Location,PARCEL,Year,DeedBkPg",
                    "returnGeometry": "false",
                    "f": "json",
                }
                try:
                    resp = await client.get(URL, params=params_gis)
                    feats = resp.json().get("features", [])
                    for f in feats:
                        attrs = f.get("attributes") or {}
                        norm_rec = _woodford_situs(attrs.get("Location"))
                        if norm_rec == norm_addr:
                            records.append(self._map_record(attrs, addr))
                            break
                except Exception as exc:
                    logger.warning("[%s] Address lookup failed for %s: %s", self.source_key, addr, exc)

            # Name queries
            for name in search_names[:limit]:
                clean_search = name.strip().upper()
                if not clean_search:
                    continue
                parts = [p.strip() for p in clean_search.replace(",", " ").split() if p.strip()]
                if not parts:
                    continue
                
                # Query Esri Name
                where = " AND ".join(f"Name LIKE '%{p}%'" for p in parts)
                params_gis = {
                    "where": where,
                    "outFields": "Name,Location,PARCEL,Year,DeedBkPg",
                    "returnGeometry": "false",
                    "f": "json",
                }
                try:
                    resp = await client.get(URL, params=params_gis)
                    feats = resp.json().get("features", [])
                    for f in feats:
                        attrs = f.get("attributes") or {}
                        records.append(self._map_record(attrs, name))
                        break
                except Exception as exc:
                    logger.warning("[%s] Name lookup failed for %s: %s", self.source_key, name, exc)

        logger.info("[%s] Esri REST match completed: found %d records", self.source_key, len(records))
        return records

    def _map_record(self, r: dict[str, Any], search_query: str) -> RawRecord:
        """Map GIS raw columns to standardized Lead schema."""
        year_built = r.get("Year")
        year_built_int = None
        if year_built and str(year_built).isdigit():
            year_built_int = int(year_built)

        situs = _woodford_situs(r.get("Location"))

        data = {
            "search_query": search_query,
            "county": self.county_name,
            "source": "woodford_gis_rest",
            "owner_name": (r.get("Name") or "").strip(),
            "property_address": situs,
            "parcel_number": (r.get("PARCEL") or "").strip(),
            "year_built": year_built_int,
            "deed_reference": (r.get("DeedBkPg") or "").strip(),
        }
        return RawRecord(source_key=self.source_key, data=data)
