"""Scott County PVA (Georgetown) — High-speed, Cloudflare-bypassing GIS connector."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Browser

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector
from app.models import RawRecord
from app.pipeline.property_address import normalize_property_address

logger = logging.getLogger(__name__)

CACHE_PATH = Path("/tmp/scott_pva_cache.json")
CACHE_DURATION_SEC = 24 * 3600  # 24 hours


@register
class ScottPVAConnector(BasePVAConnector):
    source_key = "scott_pva"
    jurisdiction = "KY-Scott"
    county_name = "Scott"
    city_name = "GEORGETOWN"
    default_schedule = "0 7 * * *"

    # Shared class-level memory cache across fetch calls in the same container session
    _memory_cache: list[dict[str, Any]] | None = None

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        """Fetch PVA records using high-speed GIS database fallback to bypass Cloudflare."""
        search_addresses = params.get("addresses", [])
        search_names = params.get("names", [])
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        try:
            db = await self._get_cached_database()
        except Exception as exc:
            logger.warning(
                "[%s] GIS database fetch failed: %s. Falling back to Playwright qPublic.",
                self.source_key,
                exc,
            )
            # If the GSCPC GIS server is totally down, fall back to our parent's Playwright qPublic lookup
            from app.connectors.residential.qpublic_pva import QPublicPVAConnector
            # Instantiate QPublicPVAConnector dynamically to delegate
            fallback = QPublicPVAConnector()
            fallback.qpublic_app = "ScottCountyKY"
            fallback.county_name = "Scott"
            fallback.source_key = "scott_pva"
            return await fallback.fetch(browser, params)

        logger.info("[%s] Matching %d addresses and %d names against GIS database...", 
                    self.source_key, len(search_addresses), len(search_names))

        # Match addresses
        for addr in search_addresses[:limit]:
            norm_search = normalize_property_address(addr)
            if not norm_search:
                continue
            for r in db:
                norm_rec = normalize_property_address(r.get("Complete_A"))
                if norm_rec == norm_search:
                    records.append(self._map_record(r, addr))
                    break

        # Match names (KCOJ party names)
        for name in search_names[:limit]:
            clean_search = name.strip().upper()
            if not clean_search:
                continue
            # Handle LastName, FirstName splits for robust matching
            parts = [p.strip() for p in clean_search.replace(",", " ").split() if p.strip()]
            if not parts:
                continue
            for r in db:
                owner = (r.get("Name1") or "").strip().upper()
                if all(p in owner for p in parts):
                    records.append(self._map_record(r, name))
                    break

        logger.info("[%s] GIS match completed: found %d records", self.source_key, len(records))
        return records

    async def _get_cached_database(self) -> list[dict[str, Any]]:
        """Get or download the GSCPC parcels database."""
        if ScottPVAConnector._memory_cache is not None:
            return ScottPVAConnector._memory_cache

        # Check disk cache
        if CACHE_PATH.exists():
            mtime = CACHE_PATH.stat().st_mtime
            if time.time() - mtime < CACHE_DURATION_SEC:
                try:
                    with open(CACHE_PATH, "r") as f:
                        data = json.load(f)
                        if data and isinstance(data, list):
                            logger.info("[%s] Loaded %d records from disk cache", self.source_key, len(data))
                            ScottPVAConnector._memory_cache = data
                            return data
                except Exception as exc:
                    logger.warning("[%s] Failed to read disk cache: %s", self.source_key, exc)

        # Download from GSCPC GIS REST
        logger.info("[%s] Downloading full GSCPC GIS database...", self.source_key)
        URL = "https://gis.gscplanning.com/arcgis/rest/services/Parcels/MapServer/1/query"

        # 1. Fetch all OBJECTIDs backwards
        ids = []
        async with httpx.AsyncClient(timeout=20) as client:
            last_id = 10_000_000_000  # Start above any OBJECTID (GIS range shifts over time)
            retry_count = 0
            while True:
                where = f"OBJECTID < {last_id}"
                params = {
                    "where": where,
                    "outFields": "OBJECTID",
                    "orderByFields": "OBJECTID DESC",
                    "resultRecordCount": 1000,
                    "f": "json",
                }
                try:
                    resp = await client.get(URL, params=params)
                    data = resp.json()
                    features = data.get("features", [])
                    if not features:
                        break
                    batch_ids = [f["attributes"]["OBJECTID"] for f in features]
                    ids.extend(batch_ids)
                    last_id = batch_ids[-1]
                    retry_count = 0  # Reset retry
                    if len(batch_ids) < 1000:
                        break
                except Exception as exc:
                    if retry_count < 3:
                        retry_count += 1
                        logger.warning("[%s] Retry %d fetching IDs: %s", self.source_key, retry_count, exc)
                        await asyncio.sleep(2)
                        continue
                    logger.warning(
                        "[%s] Failed to fetch all IDs: %s. Continuing with %d IDs.",
                        self.source_key,
                        exc,
                        len(ids),
                    )
                    break

        if not ids:
            raise RuntimeError("No OBJECTIDs returned from GSCPC")

        # 2. Fetch all columns for all ranges in parallel
        logger.info("[%s] Fetching columns for %d records in parallel...", self.source_key, len(ids))
        records = []
        async with httpx.AsyncClient(timeout=30) as client:
            tasks = []
            chunk_size = 1000
            for i in range(0, len(ids), chunk_size):
                chunk = ids[i : i + chunk_size]
                min_id = chunk[-1]
                max_id = chunk[0]

                async def fetch_range_with_retry(min_val, max_val):
                    where = f"OBJECTID >= {min_val} AND OBJECTID <= {max_val}"
                    params = {
                        "where": where,
                        "outFields": "Name1,Complete_A,YearBuilt,MapNumber,fcv,sqft,SalePrice,SaleDate,OBJECTID,MailAddress",
                        "resultRecordCount": 1000,
                        "f": "json",
                    }
                    for attempt in range(4):
                        try:
                            r = await client.get(URL, params=params)
                            return r.json().get("features", [])
                        except Exception as e:
                            if attempt == 3:
                                logger.warning(
                                    "[%s] Failed range %d-%d after 4 attempts: %s",
                                    self.source_key,
                                    min_val,
                                    max_val,
                                    e,
                                )
                                return []
                            await asyncio.sleep(1.5 * (attempt + 1))

                tasks.append(fetch_range_with_retry(min_id, max_id))

            results = await asyncio.gather(*tasks)
            for r in results:
                for f in r:
                    attrs = f.get("attributes") or {}
                    records.append(attrs)

        # Cache on disk and memory
        if records:
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(CACHE_PATH, "w") as f:
                    json.dump(records, f)
                logger.info("[%s] Cached %d records to disk", self.source_key, len(records))
            except Exception as exc:
                logger.warning("[%s] Failed to write disk cache: %s", self.source_key, exc)

            ScottPVAConnector._memory_cache = records
            return records

        raise RuntimeError("No records fetched from GSCPC GIS")

    def _map_record(self, r: dict[str, Any], search_query: str) -> RawRecord:
        """Map GIS raw columns to standardized Lead schema."""
        sale_date = r.get("SaleDate") or ""
        sale_year = None
        if sale_date:
            m = re.search(r"(20\d{2}|19\d{2})", str(sale_date))
            if m:
                sale_year = int(m.group(1))

        fcv = r.get("fcv")
        assessed_value = float(fcv) if fcv is not None else None

        sqft = r.get("sqft")
        building_sqft = int(sqft) if sqft is not None else None

        year_built = r.get("YearBuilt")
        year_built_int = None
        if year_built and str(year_built).isdigit():
            year_built_int = int(year_built)

        data = {
            "search_query": search_query,
            "county": self.county_name,
            "source": "qpublic_gis_cache",
            "owner_name": (r.get("Name1") or "").strip(),
            "property_address": normalize_property_address(r.get("Complete_A")),
            "parcel_number": (r.get("MapNumber") or "").strip(),
            "building_sqft": building_sqft,
            "year_built": year_built_int,
            "assessed_value": assessed_value,
            "last_sale_date": sale_date,
            "last_sale_price": r.get("SalePrice"),
            "last_sale_year": sale_year,
            "mailing_address": (r.get("MailAddress") or "").strip(),
        }
        return RawRecord(source_key=self.source_key, data=data)
