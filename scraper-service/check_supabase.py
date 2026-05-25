import os
import asyncio
from supabase import create_client

async def check():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Check for ALL leads, not just today
    res = supabase.table("ft_leads").select("jurisdiction, lead_type").execute()
    
    stats = {}
    for row in res.data:
        k = (row['jurisdiction'], row['lead_type'])
        stats[k] = stats.get(k, 0) + 1
        
    for (jur, lt), count in sorted(stats.items()):
        print(f"{jur} | {lt}: {count} leads")

if __name__ == "__main__":
    asyncio.run(check())
