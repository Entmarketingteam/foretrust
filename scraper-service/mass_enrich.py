"""Mass Enrichment Orchestrator (JSONB Optimized).
"""

from __future__ import annotations
import os
import asyncio
import logging
from supabase import create_client
from app.browser import create_browser
from app.connectors.registry import get_connector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

async def run_enrichment():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # 1. Fetch leads where raw_payload doesn't have pva_enriched flag
    res = supabase.table("ft_leads").select("*").filter("raw_payload->>pva_enriched", "is", "null").limit(50).execute()
    leads = res.data
    logger.info(f"Found {len(leads)} leads needing enrichment.")
    
    if not leads: return

    async with create_browser(headless=True) as browser:
        for lead in leads:
            jur = lead['jurisdiction']
            addr = lead['property_address']
            if not addr or addr == "Unknown": continue
            
            connector_key = jur.lower().replace("ky-", "") + "_pva"
            connector = get_connector(connector_key)
            if not connector: continue
                
            logger.info(f"Enriching {addr} ({jur})...")
            try:
                # Scott PVA takes address strings
                records = await connector.fetch(browser, {"addresses": [addr], "limit": 1})
                if records:
                    enriched_data = records[0].data
                    # Add flag and update
                    payload = {**(lead.get("raw_payload") or {}), **enriched_data, "pva_enriched": True}
                    
                    # Map top-level fields for convenience
                    update_data = {
                        "raw_payload": payload,
                        "year_built": enriched_data.get("year_built"),
                        "building_sqft": enriched_data.get("building_sqft"),
                        "estimated_value": enriched_data.get("assessed_value") or enriched_data.get("price")
                    }
                    
                    supabase.table("ft_leads").update(update_data).eq("id", lead['id']).execute()
                    logger.info(f"✅ Success: {addr}")
                else:
                    # Mark as checked but not found
                    payload = {**(lead.get("raw_payload") or {}), "pva_enriched": "not_found"}
                    supabase.table("ft_leads").update({"raw_payload": payload}).eq("id", lead['id']).execute()
                    logger.warning(f"⚠️ Not found in PVA: {addr}")
                    
            except Exception as e:
                logger.error(f"❌ Failed {addr}: {e}")
            
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_enrichment())
