"""Mass Enrichment Orchestrator.

Updates existing leads with physical/equity data from the PVA.
"""

from __future__ import annotations
import os
import asyncio
import logging
from supabase import create_client
from app.browser import create_browser
from app.connectors.registry import get_connector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_enrichment():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # 1. Fetch leads needing enrichment
    res = supabase.table("ft_leads").select("*").is_("year_built", "null").execute()
    leads = res.data
    logger.info(f"Found {len(leads)} leads needing enrichment.")
    
    async with create_browser(headless=True) as browser:
        for lead in leads:
            jur = lead['jurisdiction']
            addr = lead['property_address']
            if not addr or addr == "Unknown": continue
            
            # Map jurisdiction to connector
            connector_key = jur.lower().replace("ky-", "") + "_pva"
            connector = get_connector(connector_key)
            
            if not connector:
                logger.warning(f"No connector for {connector_key}")
                continue
                
            logger.info(f"Enriching {addr} ({jur})...")
            try:
                # fetch() takes params dict with 'addresses'
                records = await connector.fetch(browser, {"addresses": [addr], "limit": 1})
                if records:
                    enriched_lead = connector.parse(records[0])
                    # Update lead in Supabase
                    supabase.table("ft_leads").update({
                        "year_built": enriched_lead.year_built,
                        "building_sqft": enriched_lead.building_sqft,
                        "estimated_value": enriched_lead.estimated_value,
                        "last_sale_date": enriched_lead.raw_payload.get("last_sale_date"),
                        "last_sale_price": enriched_lead.raw_payload.get("last_sale_price"),
                        "raw_payload": enriched_lead.raw_payload # Overwrite with enriched payload
                    }).eq("id", lead['id']).execute()
                    logger.info(f"✅ Success: {addr}")
            except Exception as e:
                logger.error(f"❌ Failed {addr}: {e}")
            
            await asyncio.sleep(2) # Prevent rate limiting

if __name__ == "__main__":
    asyncio.run(run_enrichment())
