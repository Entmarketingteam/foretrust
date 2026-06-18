#!/usr/bin/env python3
"""Rank pre-MLS deals from Supabase + optional PVA enrich. Writes exports/best-deals/."""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scraper-service"
sys.path.insert(0, str(ROOT))

from app.browser import create_browser
from app.proxy import proxy_manager
from app.pipeline.deal_package import (
    build_best_deals_package,
    lead_from_supabase_row,
    rank_deals,
    write_deal_report,
)
from app.pipeline.investment_scorer import score_from_lead_data


def load_local_csv(paths: list[Path]) -> list[dict]:
    leads: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("bill_number") or row.get("owner_name", "")
                if key in seen:
                    continue
                seen.add(key)
                data = {
                    "owner_name": row.get("owner_name"),
                    "property_address": row.get("property_address"),
                    "parcel_number": row.get("map_id"),
                    "amount_due": float(row.get("amount_due") or 0),
                    "tax_year": row.get("tax_year"),
                    "source_key": "ecclix_csv_local",
                    "bill_number": row.get("bill_number"),
                    "detail_url": row.get("detail_url"),
                }
                data["investment_scores"] = score_from_lead_data(data)
                leads.append(data)
    return leads


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build pre-MLS best deals report")
    parser.add_argument("--enrich-pva", action="store_true", help="qPublic owner lookup")
    parser.add_argument(
        "--county",
        default="scott",
        help="County for PVA enrich + report label (scott, woodford)",
    )
    parser.add_argument("--pva-limit", type=int, default=30)
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Direct connection (recommended for qPublic — proxy triggers Cloudflare)",
    )
    parser.add_argument(
        "--csv",
        action="append",
        default=[],
        help="Local delinquent tax CSV (repeatable)",
    )
    parser.add_argument(
        "--default-csv",
        action="store_true",
        help="Include exports/ecclix-imports/scott-delinquent-2025-tier-a.csv",
    )
    args = parser.parse_args()

    csv_paths = [Path(p) for p in args.csv]
    if args.default_csv:
        csv_paths.append(
            ROOT / "exports" / "ecclix-imports" / "scott-delinquent-2025-tier-a.csv"
        )

    if args.enrich_pva:
        proxy = None if args.no_proxy else proxy_manager.create_session()
        async with create_browser(proxy_session=proxy) as browser:
            result = await build_best_deals_package(
                browser,
                enrich_pva=True,
                county=args.county.lower(),
                pva_limit=args.pva_limit,
            )
            print(result)
            return

    from app.pipeline.deal_package import fetch_distress_leads

    leads = await fetch_distress_leads(county=args.county.lower())
    if not leads and csv_paths:
        leads = load_local_csv(csv_paths)
    elif csv_paths:
        local = load_local_csv(csv_paths)
        keys = {l.get("owner_name") for l in leads}
        for l in local:
            if l.get("owner_name") not in keys:
                leads.append(l)

    buckets = rank_deals(leads)
    report = write_deal_report(buckets)
    print(f"Leads: {len(leads)} → report: {report}")
    for key in ("pre_mls_homebuyer", "short_sale", "fha_203k"):
        top = buckets.get(key, [])[:5]
        if top:
            print(f"\n=== {key} (top 5) ===")
            for t in top:
                sc = t.get("investment_scores", {})
                print(
                    f"  {sc.get('pre_mls_score', 0)} | "
                    f"{t.get('owner_name')} | {t.get('property_address')} | "
                    f"${t.get('amount_due', 0):,.0f}"
                )


if __name__ == "__main__":
    asyncio.run(main())
