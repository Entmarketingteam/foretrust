"""Foretrust Monetization Tactical Sheet.

Generates a targeted 'Outreach Sheet' of the top 100 most actionable leads
based on current database inventory.
"""

from __future__ import annotations
import asyncio
import os
import pandas as pd
from app.storage.supabase_client import _get_client

async def generate_outreach_sheet():
    client = _get_client()
    resp = client.table("ft_leads").select("*").execute()
    leads = resp.data
    
    outreach_list = []
    
    for l in leads:
        payload = l.get("raw_payload") or {}
        amt_due = payload.get("amount_due", 0)
        try: amt_due = float(amt_due)
        except: amt_due = 0
        
        value = l.get("estimated_value", 0)
        try: value = float(value)
        except: value = 0
        
        # Heuristic: If value is missing, use median for the county
        if value == 0:
            county_medians = {"KY-Scott": 250000, "KY-Bourbon": 180000, "KY-Woodford": 220000, "KY-Franklin": 190000}
            value = county_medians.get(l.get("jurisdiction"), 200000)
            
        equity = value - amt_due
        
        # Filter for high motivation (Tax debt > $1000 or Probate)
        if amt_due < 1000 and l.get("lead_type") not in ["probate", "estate"]:
            continue
            
        outreach_list.append({
            "Priority": "HOT" if amt_due > 10000 else "WARM",
            "Address": l.get("property_address"),
            "Owner": l.get("owner_name"),
            "County": l.get("jurisdiction"),
            "Type": l.get("lead_type"),
            "Debt": f"${amt_due:,.2f}",
            "Est_Equity": f"${equity:,.2f}",
            "Outreach_Strategy": "Cash Offer / Wholesale" if equity > 50000 else "SubTo / Creative",
            "Lead_ID": l.get("id")
        })
        
    df = pd.DataFrame(outreach_list)
    df = df.sort_values(by="Priority", ascending=True) # HOT first
    
    output_path = "OUTREACH_TACTICAL_SHEET.csv"
    df.to_csv(output_path, index=False)
    
    print(f"✅ Tactical Outreach Sheet generated: {output_path}")
    print(f"🔥 Found {len(df)} High-Motivation Leads.")

if __name__ == "__main__":
    asyncio.run(generate_outreach_sheet())
