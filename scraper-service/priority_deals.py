import os
import asyncio
from supabase import create_client

async def generate_sheet():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Fetch all tax leads from today
    res = supabase.table("ft_leads").select("*").filter("lead_type", "eq", "tax_lien").execute()
    leads = res.data
    
    # Sort by Amount Due (stored in raw_payload -> amount_due)
    valid_leads = []
    for l in leads:
        payload = l.get("raw_payload", {})
        amt = payload.get("amount_due")
        if not amt: continue
        try:
            amt = float(amt)
        except: continue
        
        addr = l.get("property_address")
        if not addr: continue
        
        # Filter for residential-looking addresses
        if any(x in addr.upper() for x in ["TRACT", "ACRES", "PARCEL", "LANE CIRCLE"]): continue
        if addr == "Unknown" or len(addr) < 5: continue
        
        valid_leads.append({
            "address": addr,
            "owner": l.get("owner_name"),
            "amount": amt,
            "county": l.get("jurisdiction"),
            "strategy": "Wholesale / Cash Buy"
        })
        
    # Sort by amount descending
    valid_leads.sort(key=lambda x: x['amount'], reverse=True)
    
    print("\n🔥 TOP 10 PRIORITY TAX DEALS (High Balance + Residential) 🔥")
    print("-" * 60)
    for i, l in enumerate(valid_leads[:10]):
        print(f"{i+1}. {l['address']} ({l['county']})")
        print(f"   Owner: {l['owner']} | Owed: ${l['amount']:,.2f}")
        print(f"   Recommended: {l['strategy']}")
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(generate_sheet())
