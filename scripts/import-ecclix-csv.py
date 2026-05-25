#!/usr/bin/env python3
"""Import eCCLIX delinquent-tax CSV exports (table-scraper) into Foretrust.

Usage:
  doppler run --project foretrust-scraper --config dev -- \\
    python3 scripts/import-ecclix-csv.py \\
      ~/Downloads/ecclix*.csv \\
      --county scott \\
      --tier A \\
      --persist

  # Write merged ranked CSV only:
  python3 scripts/import-ecclix-csv.py ~/Downloads/ecclix*.csv --out merged.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper-service"))

from app.ingest.ecclix_csv import import_paths  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Import eCCLIX delinquent tax CSVs")
    p.add_argument("paths", nargs="+", help="CSV paths or globs")
    p.add_argument("--county", default="scott")
    p.add_argument("--tier", default="A", choices=["A", "B", "C", "all"])
    p.add_argument("--min-amount", type=float, default=500.0)
    p.add_argument("--out", help="Write merged tier CSV to this path")
    p.add_argument("--persist", action="store_true", help="Upsert leads to Supabase")
    args = p.parse_args()

    expanded: list[str] = []
    for pat in args.paths:
        hits = glob.glob(pat)
        expanded.extend(hits if hits else [pat])

    tier = "active" if args.tier == "all" else args.tier
    leads, summary = import_paths(
        expanded,
        county=args.county,
        tier=tier,
        min_amount=args.min_amount,
    )

    print("=== eCCLIX CSV Import ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "tier", "bill_number", "amount_due", "owner_name", "property_address",
            "map_id", "tax_year", "best_strategy", "wholesale_score", "detail_url",
        ]
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for lead in leads:
                d = lead.raw_payload
                w.writerow({
                    "tier": d.get("tier"),
                    "bill_number": d.get("bill_number"),
                    "amount_due": d.get("amount_due"),
                    "owner_name": d.get("owner_name"),
                    "property_address": d.get("property_address"),
                    "map_id": d.get("map_id"),
                    "tax_year": d.get("tax_year"),
                    "best_strategy": d.get("best_strategy"),
                    "wholesale_score": (d.get("investment_scores") or {}).get("wholesale_score"),
                    "detail_url": d.get("detail_url"),
                })
        print(f"Wrote {len(leads)} rows → {out}")

    print("\nTop 15 by amount due:")
    for i, lead in enumerate(leads[:15], 1):
        d = lead.raw_payload
        print(
            f"  {i:2}. ${d.get('amount_due', 0):>10,.2f} | "
            f"{(lead.owner_name or '')[:30]:30} | "
            f"{(lead.property_address or '')[:25]:25} | bill {d.get('bill_number')}"
        )

    if args.persist:
        import asyncio
        from app.storage.supabase_client import insert_leads

        n = asyncio.run(insert_leads(leads))
        print(f"\nSupabase: upserted {n} lead rows (source_key=ecclix_csv_import)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
