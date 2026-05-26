#!/usr/bin/env python3
"""Batch PVA enrichment for tax leads → Supabase join."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scraper-service"
sys.path.insert(0, str(ROOT))

from app.browser import create_browser, create_browserbase_browser
from app.config import settings
from app.pipeline.pva_enrichment import (
    enrich_leads_with_pva,
    fetch_leads_for_pva,
    persist_pva_enrichment,
)


async def main() -> None:
    p = argparse.ArgumentParser(description="PVA batch enrich tax leads")
    p.add_argument("--county", default="scott", help="scott, woodford, bourbon, franklin")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--delay", type=float, default=2.0, help="Seconds between lookups")
    p.add_argument(
        "--browserbase",
        action="store_true",
        help="Use Browserbase cloud browser (bypasses Cloudflare on qPublic)",
    )
    p.add_argument("--headed", action="store_true", help="Run local Chromium headed (non-headless)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    leads = await fetch_leads_for_pva(county=args.county, limit=args.limit)
    print(f"Fetched {len(leads)} leads needing PVA for {args.county}")

    if not leads:
        return

    use_bb = args.browserbase or bool(settings.browserbase_api_key)
    headless = not args.headed

    if use_bb and settings.browserbase_api_key:
        print("Using Browserbase for PVA lookups")
        browser_ctx = create_browserbase_browser()
    else:
        print(f"Using local Chromium (headless={headless})")
        browser_ctx = create_browser(headless=headless)

    async with browser_ctx as browser:
        leads, n = await enrich_leads_with_pva(
            browser,
            leads,
            county=args.county,
            max_enrich=args.limit,
            workers_delay=args.delay,
        )
    print(f"Enriched {n} leads")

    if args.dry_run:
        enriched = [l for l in leads if l.get("pva_enriched")]
        for row in enriched[:5]:
            sc = row.get("investment_scores") or {}
            print(
                f"  {row.get('owner_name','')[:30]} | "
                f"subto={sc.get('subto',0)} wholesale={sc.get('wholesale_score',0)} | "
                f"yr={row.get('year_built')} sale={row.get('last_sale_year')}"
            )
        return

    updated = await persist_pva_enrichment(leads)
    print(f"Persisted {updated} to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
