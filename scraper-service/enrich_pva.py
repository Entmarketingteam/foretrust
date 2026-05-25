import os
import asyncio
from supabase import create_client
from app.connectors.residential.scott_pva import ScottPVAConnector
from app.browser import create_browser

async def enrich():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Fetch Scott leads
    res = supabase.table("ft_leads").select("*").eq("jurisdiction", "KY-Scott").limit(20).execute()
    leads = res.data
    
    print(f"Enriching {len(leads)} Scott leads via Scott PVA...")
    
    async with create_browser(headless=True) as browser:
        conn = ScottPVAConnector()
        for lead in leads:
            addr = lead.get("property_address")
            if not addr or addr == "Unknown": continue
            
            print(f"PVA Check: {addr}")
            try:
                # Real enrichment would go here
                # result = await conn.fetch_one(browser, addr)
                pass
            except Exception as e:
                print(f"Failed {addr}: {e}")

if __name__ == "__main__":
    asyncio.run(enrich())
