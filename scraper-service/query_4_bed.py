import os
import asyncio
import json
from supabase import create_client

async def query_4_beds():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    # Query all pre-foreclosure and foreclosure leads for Scott and Woodford
    res = supabase.table("ft_leads")\
        .select("*")\
        .in_("jurisdiction", ["KY-Scott", "KY-Woodford"])\
        .execute()
        
    leads = res.data
    print(f"Total leads analyzed for Scott/Woodford: {len(leads)}")
    
    matches = []
    
    for lead in leads:
        payload = lead.get("raw_payload") or {}
        
        # We need to find 4-bedroom indicators.
        # It could be a string in property_facts, cells, or raw text.
        payload_str = json.dumps(payload).upper()
        
        # Check if "4 BED" or "4 BR" or "4 BEDROOM" or "4.0 BED" or "BEDROOMS: 4" is in the payload
        is_4_bed = False
        
        # 1. Check direct keys if they exist from PVA
        if str(payload.get("bedrooms")) == "4" or str(payload.get("num_bedrooms")) == "4":
            is_4_bed = True
        # 2. Check property_facts list if it exists
        elif "property_facts" in payload:
            facts = payload["property_facts"]
            if any("4 BED" in str(f).upper() or "4 BR" in str(f).upper() for f in facts):
                is_4_bed = True
        # 3. Check raw string matching as a fallback
        elif any(x in payload_str for x in ["4 BED", "4BR", "4-BED", "4.0 BED", "BEDROOMS: 4", "4 BEDROOMS", "4 BEDROOM"]):
            is_4_bed = True
            
        # Is it pre-foreclosure or foreclosure?
        lt = (lead.get("lead_type") or "").lower()
        is_pre_foreclosure = any(x in lt for x in ["pre_foreclosure", "foreclosure", "pre-foreclosure", "lp", "lis pendens"])
        
        # Let's also check if the raw payload mentions "Lis Pendens" or "Foreclosure"
        if any(x in payload_str for x in ["LIS PENDENS", "FORECLOSURE", "PRE-FORECLOSURE", "DEFAULT"]):
            is_pre_foreclosure = True

        if is_4_bed and is_pre_foreclosure:
            matches.append({
                "address": lead.get("property_address"),
                "owner": lead.get("owner_name"),
                "county": lead.get("jurisdiction"),
                "lead_type": lead.get("lead_type"),
                "payload": payload
            })

    print(f"\nFound {len(matches)} matches for 4-bedroom pre-foreclosures:")
    print("-" * 60)
    for m in matches:
        print(f"📍 ADDRESS: {m['address']} ({m['county']})")
        print(f"   Owner: {m['owner']} | Type: {m['lead_type']}")
        
        # Extract some details if available
        p = m["payload"]
        if "listed_price" in p:
            print(f"   Price/Zestimate: {p['listed_price']}")
        if "year_built" in p:
            print(f"   Year Built: {p['year_built']}")
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(query_4_beds())
