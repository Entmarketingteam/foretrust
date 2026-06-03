#!/usr/bin/env python3
"""FOIA Water Shutoff Ingestor.

Parses municipal water shutoff CSVs (Georgetown, Paris, Frankfort, Versailles)
and ingests them into Supabase `ft_leads` with `source_key=water_shutoff`.
"""

import os
import sys
import csv
import argparse
import logging
from datetime import datetime
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Ingest Water Shutoff FOIA Lists")
    parser.add_argument("file_path", type=str, help="Path to the water shutoff CSV file")
    parser.add_argument("--city", type=str, required=True, choices=["Georgetown", "Paris", "Frankfort", "Versailles"], help="Source City/County")
    return parser.parse_args()

def map_lead_type(row: dict) -> str:
    # Water shutoff is a direct proxy for vacancy
    return "vacancy"

async def main():
    args = parse_args()
    
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing Supabase credentials in environment. Ensure Doppler is active.")
        sys.exit(1)
        
    supabase = create_client(url, key)
    
    if not os.path.exists(args.file_path):
        logger.error(f"File not found: {args.file_path}")
        sys.exit(1)
        
    leads = []
    logger.info(f"Parsing shutoff list for {args.city} from {args.file_path}...")
    
    with open(args.file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Common headers or fallback to index-based mapping
            addr = row.get("Service Address") or row.get("address") or row.get("location")
            name = row.get("Account Holder") or row.get("name") or row.get("owner")
            shutoff_date = row.get("Shutoff Date") or row.get("date")
            
            if not addr:
                # Fallback to first column if header mismatch
                addr = list(row.values())[0]
                
            if not addr or len(addr.strip()) < 5:
                continue
                
            lead_data = {
                "source_key": "water_shutoff",
                "vertical": "RESIDENTIAL",
                "jurisdiction": f"KY-{args.city}",
                "lead_type": "vacancy",
                "owner_name": (name or "Unknown").strip(),
                "property_address": addr.strip(),
                "state": "KY",
                "raw_payload": {
                    "source_city": args.city,
                    "shutoff_date": shutoff_date,
                    "ingested_at": datetime.utcnow().isoformat(),
                    "original_row": row
                }
            }
            leads.append(lead_data)

    logger.info(f"Found {len(leads)} valid shutoff records. Ingesting to Supabase...")
    
    # Bulk insert with deduplication handling
    inserted_count = 0
    batch_size = 100
    for i in range(0, len(leads), batch_size):
        batch = leads[i:i+batch_size]
        try:
            res = supabase.table("ft_leads").upsert(
                batch,
                on_conflict="property_address,jurisdiction" # Deduplicate on address + county
            ).execute()
            inserted_count += len(res.data)
            logger.info(f"Ingested batch {i // batch_size + 1}: {len(res.data)} records")
        except Exception as e:
            logger.error(f"Failed to ingest batch: {e}")
            
    logger.info(f"🎉 SUCCESS: Ingested {inserted_count} total water shutoff leads.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
