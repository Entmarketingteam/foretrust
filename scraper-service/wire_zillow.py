"""Zillow Listing Bridge.

Enriches leads with live listing status and photos from Zillow.
"""

from __future__ import annotations
import os
import asyncio
import logging
from supabase import create_client
from app.connectors.residential.zillow_public import ZillowPublicConnector
from app.browser import create_browser, create_browserbase_browser
from app.proxy import proxy_manager
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def wire_zillow():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Fetch 20 priority leads without Zillow data
    res = supabase.table("ft_leads").select("*").filter("raw_payload->>zillow_checked", "is", "null").limit(20).execute()
    leads = res.data
    logger.info(f"Wiring {len(leads)} leads to Zillow API...")
    
    if not leads:
        logger.info("No leads requiring Zillow checks.")
        return

    # Choose browser connection depending on available secrets (Browserbase vs Rotating Proxies)
    use_bb = bool(settings.browserbase_api_key)
    
    if use_bb:
        logger.info("[zillow-bridge] Bypassing Akamai WAF using Browserbase Cloud Browser")
        browser_ctx = create_browserbase_browser()
    else:
        logger.info("[zillow-bridge] Bypassing Akamai WAF using local Playwright + Webshare rotating residential proxies")
        proxy_session = proxy_manager.create_session()
        browser_ctx = create_browser(proxy_session=proxy_session, headless=True)
        
    async with browser_ctx as browser:
        z_conn = ZillowPublicConnector()
        for lead in leads:
            addr = lead['property_address']
            if not addr or addr == "Unknown": 
                continue
            
            logger.info(f"Zillow Scan: {addr}...")
            try:
                # Actual Zillow Public record scan
                records = await z_conn.fetch(browser, {"addresses": [addr], "limit": 1})
                if records:
                    z_data = records[0].data
                    payload = {**(lead.get("raw_payload") or {}), **z_data, "zillow_checked": True}
                    
                    supabase.table("ft_leads").update({
                        "raw_payload": payload,
                        "estimated_value": z_data.get("listed_price") or lead.get("estimated_value")
                    }).eq("id", lead['id']).execute()
                    logger.info(f"✅ Visuals Linked: {addr}")
                else:
                    # Mark as checked but off-market/no signals
                    payload = {**(lead.get("raw_payload") or {}), "zillow_checked": "no_signals"}
                    supabase.table("ft_leads").update({"raw_payload": payload}).eq("id", lead['id']).execute()
                    logger.info(f"⚪ Off-Market (No Signals): {addr}")
            except Exception as e:
                logger.error(f"❌ Bridge Failed {addr}: {e}")
            
            await asyncio.sleep(5) # Throttling for Zillow

if __name__ == "__main__":
    asyncio.run(wire_zillow())
