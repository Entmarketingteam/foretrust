"""GIS Address Enrichment: Resolve missing property addresses using county GIS REST endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.storage.supabase_client import _get_client

logger = logging.getLogger(__name__)

# A lender named as the lead owner is the foreclosure grantee, never the
# property owner — any GIS owner-match returns the lender's own corporate
# parcel (wrong property). Skip these entirely.
LENDER_RE = re.compile(
    r"\b(BANK|CREDIT UNION|FED CR|FCU|MORTGAGE|MORTG|SAVINGS|LOAN|N\.A\.|NATIONAL ASSOCIATION)\b|\w*BANK\b", re.I
)


def _woodford_situs(v):
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


# county (as stored in jurisdiction 'KY-<County>') -> ArcGIS PVA-ownership query
# endpoint + field names. Add counties here as their endpoints are confirmed.
COUNTY_GIS = {
    "Scott": {
        "url": "http://gis.gscplanning.com/arcgis/rest/services/Parcels/MapServer/1/query",
        "name_field": "Name1",
        "addr_field": "Complete_A",
        "extra": {"fcv": "fcv", "year_built": "YearBuilt", "parcel": "MapNumber"},
    },
    "Woodford": {
        "url": "https://services9.arcgis.com/eE18Y8QhAVKzp7mP/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "name_field": "Name",
        "addr_field": "Location",
        "addr_normalize": _woodford_situs,
        "extra": {"year_built": "Year", "deed": "DeedBkPg", "parcel": "PARCEL"},
    },
    "Franklin": {
        "url": "https://wfs.schneidercorp.com/arcgis/rest/services/FranklinCountyKY_WFS/MapServer/4/query",
        "name_field": "OwnerName",
        "addr_field": "PARCEL_ID",
        "spatial_join": {
            "url": "https://kygisserver.ky.gov/arcgis/rest/services/WGS84WM_Services/Ky_911_Site_Structure_Address_Points_WGS84WM/MapServer/0/query",
            "inSR": 2246,
        },
        "extra": {"parcel": "PARCEL_ID"},
    },
}


def gis_lookup(cfg: dict, owner: str) -> tuple[str, dict] | None:
    """Return (address, extras) if the owner resolves to one address, else None."""
    if "," in owner:
        last, rest = owner.split(",", 1)
    else:
        parts = owner.split()
        last, rest = (parts[0] if parts else ""), " ".join(parts[1:])
    last = last.strip().upper()
    firsts = rest.strip().upper().split()
    if not last:
        return None
    nf = cfg["name_field"]
    where = f"{nf} LIKE '%{last}%'"
    if firsts:
        where += f" AND {nf} LIKE '%{firsts[0]}%'"
    af = cfg["addr_field"]
    norm = cfg.get("addr_normalize", lambda v: v.strip() if v else None)
    
    spatial_join = cfg.get("spatial_join")
    ret_geom = "true" if spatial_join else "false"
    
    out_fields = ",".join([nf, af, *cfg["extra"].values()])
    qs = urllib.parse.urlencode({
        "where": where, "outFields": out_fields,
        "returnGeometry": ret_geom, "f": "json",
    })
    try:
        req = urllib.request.Request(f"{cfg['url']}?{qs}", headers={"User-Agent": "foretrust-pva-gis/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            feats = json.loads(r.read()).get("features", [])
    except Exception as exc:
        logger.debug("GIS API call failed for owner %s: %s", owner, exc)
        return None
        
    rows = []
    for f in feats:
        a = f.get("attributes", {})
        cleaned = None
        
        if spatial_join:
            geom = f.get("geometry")
            if geom and geom.get("rings"):
                # Query State E911 Address Points using spatial polygon intersection
                spatial_params = {
                    "geometry": json.dumps({"rings": geom["rings"], "spatialReference": {"wkid": spatial_join["inSR"]}}),
                    "geometryType": "esriGeometryPolygon",
                    "spatialRel": "esriSpatialRelIntersects",
                    "inSR": str(spatial_join["inSR"]),
                    "outFields": "Add_Number,St_Name,St_PosTyp,Post_Comm,Post_Code",
                    "f": "json"
                }
                try:
                    spatial_qs = urllib.parse.urlencode(spatial_params)
                    spatial_req = urllib.request.Request(
                        spatial_join["url"],
                        data=spatial_qs.encode(),
                        method="POST",
                        headers={"User-Agent": "foretrust-pva-gis/1.0"}
                    )
                    with urllib.request.urlopen(spatial_req, timeout=10) as s_resp:
                        s_data = json.loads(s_resp.read())
                        s_feats = s_data.get("features", [])
                        if s_feats:
                            s_attrs = s_feats[0].get("attributes") or {}
                            num = s_attrs.get("Add_Number")
                            st = s_attrs.get("St_Name") or ""
                            typ = s_attrs.get("St_PosTyp") or ""
                            if num:
                                cleaned = f"{num} {st} {typ}".strip().upper()
                except Exception as e:
                    logger.debug("Spatial join query failed for parcel %s: %s", a.get(af), e)
        else:
            cleaned = norm(a.get(af))
            
        if cleaned:
            a["_addr"] = cleaned
            rows.append(a)
            
    addrs = {r["_addr"] for r in rows}
    if len(addrs) != 1:
        return None  # 0 = no match, >1 = ambiguous -> skip
    a = rows[0]
    extras = {k: a.get(v) for k, v in cfg["extra"].items() if a.get(v) not in (None, "")}
    return a["_addr"], extras


async def enrich_all_counties_gis(client=None) -> dict[str, int]:
    """Scan and enrich leads missing addresses across all configured counties."""
    if not client:
        client = _get_client()
    if not client:
        logger.error("Supabase client not available for GIS address enrichment.")
        return {}
        
    results = {}
    for county in COUNTY_GIS.keys():
        try:
            enriched = await enrich_county_gis(county, client)
            results[county] = enriched
        except Exception as exc:
            logger.error("GIS enrichment failed for county %s: %s", county, exc)
    return results


async def enrich_county_gis(county: str, client=None) -> int:
    """Enrich any leads missing property addresses in a specific county using GIS REST endpoints."""
    if not client:
        client = _get_client()
    if not client:
        return 0
        
    cfg = COUNTY_GIS.get(county)
    if not cfg:
        logger.warning("No GIS config for county %s", county)
        return 0
        
    logger.info("[gis-enrich] Scanning %s County leads missing addresses...", county)
    
    leads = []
    offset = 0
    while True:
        try:
            # Query for leads missing property addresses (batch of 1000)
            q = (
                client.table("ft_leads")
                .select("id, owner_name, property_address, raw_payload")
                .eq("jurisdiction", f"KY-{county}")
            )
            batch = q.range(offset, offset + 999).execute().data or []
            if not batch:
                break
            for row in batch:
                owner = (row.get("owner_name") or "").strip()
                addr = (row.get("property_address") or "").strip()
                if not owner:
                    continue
                if not addr or addr == "" or addr.upper() == "ALL PROPERTIES OWNED":
                    leads.append({"id": row["id"], "owner_name": owner, "raw_payload": row.get("raw_payload") or {}})
            if len(batch) < 1000:
                break
            offset += 1000
        except Exception as exc:
            logger.warning("[gis-enrich] failed to fetch batch at offset %d: %s", offset, exc)
            break
            
    if not leads:
        logger.info("[gis-enrich] No leads missing address in %s county.", county)
        return 0
        
    logger.info("[gis-enrich] Found %d candidate leads in %s county", len(leads), county)
    
    enriched_count = 0
    updates = []
    
    for lead in leads:
        owner = lead["owner_name"]
        if LENDER_RE.search(owner):
            continue  # lender lead
            
        res = await asyncio.to_thread(gis_lookup, cfg, owner)
        if res:
            addr, extras = res
            updates.append((lead["id"], addr, extras, lead["raw_payload"]))
            enriched_count += 1
            logger.info("[gis-enrich] Matched: %s -> %s", owner[:30], addr)
            await asyncio.sleep(0.15)
            
    updated_count = 0
    for lid, addr, extras, raw_payload in updates:
        try:
            if isinstance(raw_payload, str):
                raw_payload = {}
            payload = {
                **raw_payload,
                **extras,
                "pva_gis_enriched": True,
                "gis_enriched_at": datetime.now(timezone.utc).isoformat()
            }
            patch = {
                "property_address": addr,
                "raw_payload": payload,
            }
            if extras.get("parcel"):
                patch["parcel_number"] = extras["parcel"]
            if extras.get("year_built"):
                try:
                    patch["year_built"] = int(extras["year_built"])
                except Exception:
                    pass
            if extras.get("fcv"):
                try:
                    patch["estimated_value"] = float(extras["fcv"])
                except Exception:
                    pass
                    
            client.table("ft_leads").update(patch).eq("id", lid).execute()
            updated_count += 1
        except Exception as exc:
            logger.warning("[gis-enrich] Failed to update lead %s: %s", lid, exc)
            
    logger.info("[gis-enrich] Completed %s County: filled %d/%d addresses", county, updated_count, len(leads))
    return updated_count
