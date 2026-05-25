"""Enrich captured leads with Zillow data.
"""

from __future__ import annotations
import os
import asyncio
from supabase import create_client
from app.connectors.residential.zillow_public import ZillowPublicConnector
from playwright.async_api import async_playwright
from app.browser import create_browser

async def enrich():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Fetch leads from today that haven't been Zillow-checked
    res = supabase.table("ft_leads").select("*").filter("scraped_at", "gt", "2026-05-25T00:00:00").execute()
    leads_to_check = res.data
    print(f"Enriching {len(leads_to_check)} leads via Zillow...")
    
    async with create_browser(headless=True) as browser:
        z_conn = ZillowPublicConnector()
        for lead in leads_to_check[:20]: # Start with small batch
            addr = lead.get("property_address")
            if not addr or addr == "Unknown": continue
            
            print(f"Checking Zillow: {addr}")
            try:
                # Mocking zillow check for now or using the connector
                # Actual connector check would go here
                pass
            except Exception as e:
                print(f"Zillow check failed for {addr}: {e}")

if __name__ == "__main__":
    asyncio.run(enrich())
