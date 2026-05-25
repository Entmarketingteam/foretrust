import os
import asyncio
from supabase import create_client

async def analyze():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    res = supabase.table("ft_leads").select("jurisdiction, property_address, lead_type, raw_payload").execute()
    
    subto = []
    equity_trap = []
    
    for lead in res.data:
        payload = lead.get("raw_payload", {})
        addr = lead.get("property_address")
        
        # Check for 2020/2021 purchase dates in 'date' or 'raw_payload'
        date_str = payload.get("date", "")
        if "2020" in date_str or "2021" in date_str:
            subto.append(lead)
            
        # Equity Trap Logic: If assessed value is close to purchase price
        # (Assuming we have these fields in raw_payload)
        try:
            val = float(payload.get("assessed_value", 0))
            price = float(payload.get("purchase_price", 0))
            if val > 0 and price > 0 and (val - price) < (val * 0.1):
                equity_trap.append(lead)
        except: pass

    print(f"--- CREATIVE FINANCE ANALYSIS ---")
    print(f"Total Leads Analyzed: {len(res.data)}")
    print(f"🔥 SubTo Candidates (2020-2021 Rates): {len(subto)}")
    print(f"🔥 Equity Trapped Candidates: {len(equity_trap)}")
    
    if subto:
        print("\nTop SubTo Targets:")
        for s in subto[:5]:
            print(f"- {s['property_address']} ({s['jurisdiction']})")

if __name__ == "__main__":
    asyncio.run(analyze())
