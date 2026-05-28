"""Foretrust Revenue Intelligence Engine.

Analyzes the current 1,694 leads in Supabase and generates a 'Money Sheet'
of deals with the highest equity-to-distress ratio.
"""

from __future__ import annotations
import os
import asyncio
import pandas as pd
from app.storage.supabase_client import _get_client

async def generate_revenue_report():
    print("🚀 Launching Revenue Intelligence Engine...")
    client = _get_client()
    
    # 1. Fetch all leads with enough data to analyze
    # We want tax liens (distress) and estimated_value (equity potential)
    resp = client.table("ft_leads").select("*").execute()
    leads = resp.data
    
    print(f"📊 Analyzing {len(leads)} database records...")
    
    report_data = []
    
    for l in leads:
        payload = l.get("raw_payload") or {}
        
        # Calculate Distress
        amt_due = payload.get("amount_due") or l.get("estimated_value") if l.get("lead_type") == "tax_lien" else 0
        try: amt_due = float(amt_due)
        except: amt_due = 0
        
        # Calculate Value / Equity Potential
        value = l.get("estimated_value")
        try: value = float(value)
        except: value = 0
        
        # Skip garbage or zero-value records
        if value < 10000 and amt_due < 100:
            continue
            
        # Strategy Logic
        strategy = "Wholesale / Cash"
        if l.get("lead_type") == "tax_lien" and amt_due > 5000:
            strategy = "High Motivation (Tax Buyout)"
        elif l.get("lead_type") in ["probate", "estate"]:
            strategy = "Probate / Creative"
        elif "2020" in str(payload.get("recorded_date")) or "2021" in str(payload.get("recorded_date")):
            strategy = "SubTo (Low Rate Potential)"
            
        # Equity Estimate (Conservative)
        equity = value - amt_due if value > 0 else 0
        
        report_data.append({
            "Address": l.get("property_address"),
            "Owner": l.get("owner_name"),
            "County": l.get("jurisdiction"),
            "Signal": l.get("lead_type"),
            "Distress ($)": amt_due,
            "Est. Value ($)": value,
            "Est. Equity ($)": equity,
            "Strategy": strategy,
            "ID": l.get("id")
        })
        
    df = pd.DataFrame(report_data)
    
    # Rank by 'Money Score' (High Equity + High Distress)
    df["Money Score"] = (df["Distress ($)"] / 1000) + (df["Est. Equity ($)"] / 50000)
    df = df.sort_values(by="Money Score", ascending=False)
    
    # Save to CSV
    output_path = "REVENUE_MONEY_SHEET.csv"
    df.to_csv(output_path, index=False)
    
    print(f"✅ Success! Revenue report saved to: {output_path}")
    print("\n🔥 TOP 5 HIGH-REVENUE DEALS FOUND:")
    for i, row in df.head(5).iterrows():
        print(f"{i+1}. {row['Address']} ({row['County']}) | Strategy: {row['Strategy']}")
        print(f"   Owed: ${row['Distress ($)']:,.2f} | Equity: ${row['Est. Equity ($)']:,.2f}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(generate_revenue_report())
