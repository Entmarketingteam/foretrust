import os
import asyncio
from supabase import create_client

async def analyze():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Query leads where pva_enriched is true
    res = supabase.table("ft_leads").select("*").filter("raw_payload->>pva_enriched", "eq", "true").execute()
    
    subto = []
    equity_trap = []
    
    print(f"--- REAL-TIME CREATIVE FINANCE ANALYSIS ---")
    print(f"Enriched leads found: {len(res.data)}")
    
    for lead in res.data:
        payload = lead.get("raw_payload", {})
        addr = lead.get("property_address")
        
        # Pace Morby SubTo: 2020-2021 purchase dates
        sale_date = payload.get("last_sale_date", "")
        if any(year in str(sale_date) for year in ["2020", "2021"]):
            subto.append(lead)
            
        # Equity Trap: Price vs Assessed
        try:
            val = float(payload.get("assessed_value", 0))
            price = float(payload.get("last_sale_price", 0))
            if val > 0 and price > 0:
                equity = (val - price) / val
                if equity < 0.1:
                    equity_trap.append(lead)
        except: pass

    print(f"🔥 SubTo Candidates (3% Interest Rate Potential): {len(subto)}")
    print(f"🔥 Equity Trapped Candidates: {len(equity_trap)}")
    
    if subto:
        print("\nTOP SUBTO OPPORTUNITIES:")
        for s in subto[:10]:
            print(f"- {s['property_address']} (Jurisdiction: {s['jurisdiction']})")

if __name__ == "__main__":
    asyncio.run(analyze())
