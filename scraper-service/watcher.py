"""Institutional Watchdog & Deal Reporter.

Runs in background, monitors Supabase, and updates LIVE_DEAL_SHEET.md.
"""

from __future__ import annotations
import os
import asyncio
import time
import logging
from supabase import create_client

# Disable buffering
import sys

# Suppress debug logs
logging.getLogger("httpx").setLevel(logging.WARNING)

async def watch():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    md_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "LIVE_DEAL_SHEET.md")
    
    print(f"Watcher started. Writing to {md_path}")
    
    while True:
        try:
            # 1. Get ALL leads
            res = supabase.table("ft_leads").select("*").execute()
            leads = res.data
            
            stats = {}
            for l in leads:
                k = (l['jurisdiction'], l['lead_type'])
                stats[k] = stats.get(k, 0) + 1
            
            # 2. Get Top Deals
            valid_deals = []
            for tl in leads:
                if tl['lead_type'] != 'tax_lien': continue
                
                p = tl.get("raw_payload", {})
                amt = p.get("amount_due")
                if amt is None: continue
                
                try: amt = float(amt)
                except: continue
                
                if amt > 500:
                    valid_deals.append({
                        "addr": tl['property_address'], 
                        "jur": tl['jurisdiction'], 
                        "amt": amt, 
                        "owner": tl['owner_name']
                    })
            
            valid_deals.sort(key=lambda x: x['amt'], reverse=True)
            
            # 3. Write Markdown
            with open(md_path, "w") as f:
                f.write("# 🔥 LIVE REI DEAL SHEET (Institutional Ground Truth) 🔥\n\n")
                f.write(f"**Last Updated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Total Database Inventory:** {len(leads)}\n\n")
                
                f.write("## 📈 Inventory Summary\n")
                f.write("| Jurisdiction | Signal Type | Count |\n| :--- | :--- | :--- |\n")
                for (jur, lt), count in sorted(stats.items()):
                    f.write(f"| {jur} | {lt} | {count} |\n")
                
                f.write("\n## 💰 Top Priority Deals (High Balance Tax & Distress)\n")
                f.write("| Rank | Address | County | Balance | Strategy |\n| :--- | :--- | :--- | :--- | :--- |\n")
                for i, d in enumerate(valid_deals[:50]):
                    f.write(f"| {i+1} | {d['addr']} | {d['jur']} | ${d['amt']:,.2f} | Wholesale / SubTo |\n")
            
            print(f"[{time.strftime('%H:%M:%S')}] Deal sheet updated with {len(leads)} total inventory.", flush=True)
        except Exception as e:
            print(f"Watcher Error: {e}", flush=True)
            
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(watch())
