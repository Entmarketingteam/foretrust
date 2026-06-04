import os
import asyncio
from supabase import create_client

async def find_large_homes():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    res = supabase.table("ft_leads")\
        .select("*")\
        .in_("jurisdiction", ["KY-Scott", "KY-Woodford"])\
        .not_.is_("year_built", "null")\
        .execute()
        
    leads = res.data
    print(f"Analyzing {len(leads)} enriched local leads for 4-bedroom potential (> 2000 SQFT)...")
    print("=" * 80)
    
    candidates = []
    for l in leads:
        sqft = l.get("building_sqft")
        try:
            sqft = int(sqft) if sqft else 0
        except: sqft = 0
        
        if sqft >= 2000:
            p = l.get("raw_payload") or {}
            
            last_sale_date = p.get("last_sale_date", "Unknown")
            last_sale_price = p.get("last_sale_price")
            
            rate_est = "N/A"
            if last_sale_date and ("2020" in str(last_sale_date) or "2021" in str(last_sale_date)):
                rate_est = "🔥 2.5% - 3.5% (Prime SubTo)"
            elif last_sale_date and ("2022" in str(last_sale_date)):
                rate_est = "⚡ 3.5% - 5.0% (Good SubTo)"
                
            candidates.append({
                "address": l.get("property_address"),
                "sqft": sqft,
                "year": l.get("year_built"),
                "owner": l.get("owner_name"),
                "value": l.get("estimated_value"),
                "sale_date": last_sale_date,
                "sale_price": last_sale_price,
                "rate_est": rate_est,
                "county": l.get("jurisdiction")
            })
            
    candidates.sort(key=lambda x: x['sqft'], reverse=True)
    
    for i, c in enumerate(candidates):
        print(f"{i+1}. 🏡 {c['address']} ({c['county']})")
        print(f"   Size: {c['sqft']:,} SQFT | Year Built: {c['year']}")
        print(f"   Owner: {c['owner'].title()}")
        
        price_str = f"${c['sale_price']:,.2f}" if c['sale_price'] is not None else "Unknown"
        print(f"   Last Sale: {c['sale_date']} for {price_str}")
        print(f"   SubTo Rating: {c['rate_est']}")
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(find_large_homes())
