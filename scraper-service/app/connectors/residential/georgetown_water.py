"""Georgetown Municipal Water / GUS — outage GIS + shutoff intel.

Shutoff *lists* for non-payment are not published daily online; GMWSS mails
disconnect notices. Track:
  - ArcGIS water outage polygons (vacancy/distress proxy)
  - FOIA requests to City Clerk + GMWSS for disconnect rolls

ArcGIS: https://gis.georgetown.org/arcgis/rest/services/GUS/WaterOutage_FeatureService/MapServer/3
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical

logger = logging.getLogger(__name__)

OUTAGE_QUERY_URL = (
    "https://gis.georgetown.org/arcgis/rest/services/GUS/"
    "WaterOutage_FeatureService/MapServer/3/query"
)


@register
class GeorgetownWaterConnector(BaseConnector):
    source_key = "georgetown_water"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Scott"
    base_url = "https://gis.georgetown.org"
    default_schedule = "0 8 * * *"
    respects_robots = True

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        del browser
        records: list[RawRecord] = []
        try:
            records.extend(await self._fetch_active_outages(params))
        except Exception as exc:
            logger.error("[georgetown_water] outage query failed: %s", exc)
        foia_path = params.get("foia_import_path")
        if foia_path:
            records.extend(self._import_foia_csv(foia_path))
        return records

    async def _fetch_active_outages(self, params: dict[str, Any]) -> list[RawRecord]:
        """Query ArcGIS for ActiveOutage = Yes features."""
        limit = int(params.get("limit", 500))
        query = {
            "where": "ActiveOutage='Yes'",
            "outFields": (
                "OBJECTID,ActiveOutage,CusOut,CusRestored,StartTime,ETOR,"
                "PublicNotes,BoilWaterNotice,Verified,CrewStatus"
            ),
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": str(min(limit, 2000)),
        }
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(OUTAGE_QUERY_URL, params=query)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features") or []
        records: list[RawRecord] = []
        for feat in features:
            attrs = feat.get("attributes") or {}
            geom = feat.get("geometry") or {}
            cus_out = attrs.get("CusOut") or 0
            notes = (attrs.get("PublicNotes") or "").strip()
            payload = {
                "signal_channel": "water_outage",
                "active_outage": attrs.get("ActiveOutage"),
                "customers_out": cus_out,
                "customers_restored": attrs.get("CusRestored"),
                "start_time": attrs.get("StartTime"),
                "etor": attrs.get("ETOR"),
                "public_notes": notes,
                "boil_water": attrs.get("BoilWaterNotice"),
                "outage_type": attrs.get("Verified"),
                "crew_status": attrs.get("CrewStatus"),
                "centroid": _centroid(geom),
                "row_text": f"Water outage CusOut={cus_out} {notes}"[:500],
            }
            records.append(RawRecord(source_key=self.source_key, data=payload))
        logger.info("[georgetown_water] active outages: %d", len(records))
        return records

    def _import_foia_csv(self, path: str) -> list[RawRecord]:
        """Manual FOIA disconnect list → leads (CSV: address, owner, disconnect_date)."""
        import csv
        from pathlib import Path

        records: list[RawRecord] = []
        p = Path(path)
        if not p.exists():
            logger.warning("[georgetown_water] FOIA file missing: %s", path)
            return records
        with p.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                addr = (row.get("property_address") or row.get("address") or "").strip()
                if not addr:
                    continue
                records.append(
                    RawRecord(
                        source_key=self.source_key,
                        data={
                            "signal_channel": "water_shutoff",
                            "owner_name": row.get("owner_name") or row.get("owner"),
                            "property_address": addr,
                            "disconnect_date": row.get("disconnect_date") or row.get("date"),
                            "account_number": row.get("account") or row.get("account_number"),
                            "foia_import": True,
                            "row_text": f"Water shutoff FOIA {addr}",
                        },
                    )
                )
        logger.info("[georgetown_water] FOIA import: %d rows", len(records))
        return records

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        channel = d.get("signal_channel", "water_outage")
        lead_type = LeadType.VACANCY if channel == "water_outage" else LeadType.CODE_VIOLATION
        if channel == "water_shutoff":
            lead_type = LeadType.VACANCY
        addr = d.get("property_address") or ""
        if not addr and d.get("centroid"):
            lat, lon = d["centroid"]
            addr = f"Near {lat:.5f},{lon:.5f} (GIS outage — drive-by / reverse geo)"
        return Lead(
            source_key=self.source_key,
            vertical=self.vertical,
            jurisdiction=self.jurisdiction,
            lead_type=lead_type,
            owner_name=d.get("owner_name"),
            property_address=addr or None,
            city="Georgetown",
            state="KY",
            case_id=str(d.get("OBJECTID") or d.get("account_number") or ""),
            raw_payload={**d, "action": "skip_trace_or_driveby"},
            scraped_at=datetime.utcnow(),
        )


def _centroid(geom: dict) -> tuple[float, float] | None:
    rings = geom.get("rings")
    if not rings or not rings[0]:
        return None
    pts = rings[0]
    if not pts:
        return None
    lat = sum(p[1] for p in pts) / len(pts)
    lon = sum(p[0] for p in pts) / len(pts)
    return (lat, lon)
