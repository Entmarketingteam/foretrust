"""Institutional Watchdog & Deal Reporter.

Runs in background, monitors Supabase, and updates LIVE_DEAL_SHEET.md.
"""

from __future__ import annotations
import os
import asyncio
import time
from supabase import create_client

async def watch():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(url, key)
    
    while True:
        try:
            # 1. Get Stats
            res = supabase.table("ft_leads").select("jurisdiction, lead_type, source_key").filter("scraped_at", "gt", "2026-05-25T00:00:00").execute()
            leads = res.data
            
            stats = {}
            for l in leads:
                k = (l['jurisdiction'], l['lead_type'])
                stats[k] = stats.get(k, 0) + 1
            
            # 2. Get Top Deals
            tax_leads = [l for l in leads if l['lead_type'] == 'tax_lien']
            valid_deals = []
            for tl in tax_leads:
                p = tl.get("raw_payload", {})
                amt = p.get("amount_due", 0)
                try: amt = float(amt)
                except: continue
                if amt > 500:
                    valid_deals.append({"addr": tl['property_address'], "jur": tl['jurisdiction'], "amt": amt, "owner": tl['owner_name']})
            
            valid_deals.sort(key=lambda x: x['amt'], reverse=True)
            
            # 3. Write Markdown
            with open("LIVE_DEAL_SHEET.md", "w") as f:
                f.write("# 🔥 LIVE REI DEAL SHEET (Real-Time) 🔥\n\n")
                f.write(f"**Last Updated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Total Captured Today:** {len(leads)}\n\n")
                
                f.write("## 📈 Inventory Summary\n")
                f.write("| Jurisdiction | Type | Count |\n| :--- | :--- | :--- |\n")
                for (jur, lt), count in sorted(stats.items()):
                    f.write(f"| {jur} | {lt} | {count} |\n")
                
                f.write("\n## 💰 Top Priority Tax Deals\n")
                f.write("| Rank | Address | County | Balance | Strategy |\n| :--- | :--- | :--- | :--- | :--- |\n")
                for i, d in enumerate(valid_deals[:20]):
                    f.write(f"| {i+1} | {d['addr']} | {d['jur']} | ${d['amt']:,.2f} | Wholesale |\n")
            
            print(f"[{time.strftime('%H:%M:%S')}] Deal sheet updated with {len(leads)} leads.")
        except Exception as e:
            print(f"Watcher Error: {e}")
            
        await asyncio.sleep(60) # Refresh every minute

if __name__ == "__main__":
    asyncio.run(watch())
