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
    p.add_argument(
        "--no-proxy",
        action="store_true",
        help="Direct connection (recommended for qPublic)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--chunk-size",
        type=int,
        default=10,
        help="Fresh browser session every N leads (avoids Browserbase mid-batch disconnect)",
    )
    args = p.parse_args()

    leads = await fetch_leads_for_pva(county=args.county, limit=args.limit)
    print(f"Fetched {len(leads)} leads needing PVA for {args.county}")

    if not leads:
        return

    use_bb = args.browserbase or (bool(settings.browserbase_api_key) and not args.no_proxy)
    headless = not args.headed
    chunk_size = max(1, args.chunk_size)
    total_enriched = 0
    total_persisted = 0

    for start in range(0, len(leads), chunk_size):
        chunk = leads[start : start + chunk_size]
        print(f"\n--- chunk {start // chunk_size + 1} ({len(chunk)} leads) ---")

        if use_bb and settings.browserbase_api_key:
            print("Using Browserbase for PVA lookups")
            browser_ctx = create_browserbase_browser()
        else:
            proxy_note = "no proxy" if args.no_proxy else "with proxy"
            print(f"Using local Chromium (headless={headless}, {proxy_note})")
            from app.proxy import proxy_manager

            proxy = None if args.no_proxy else proxy_manager.create_session()
            browser_ctx = create_browser(headless=headless, proxy_session=proxy)

        try:
            async with browser_ctx as browser:
                chunk, n = await enrich_leads_with_pva(
                    browser,
                    chunk,
                    county=args.county,
                    max_enrich=len(chunk),
                    workers_delay=args.delay,
                )
        except Exception as exc:
            err = str(exc)
            if "402" in err or "Payment Required" in err:
                print(
                    f"Browserbase session limit (402) — stopping after "
                    f"{total_enriched} enriched. Top up Browserbase or use --no-proxy."
                )
                break
            raise
        leads[start : start + len(chunk)] = chunk
        total_enriched += n
        print(f"Chunk enriched {n}/{len(chunk)}")

        if args.dry_run:
            continue

        updated = await persist_pva_enrichment(chunk)
        total_persisted += updated
        print(f"Chunk persisted {updated}")

    print(f"\nTotal enriched {total_enriched}/{len(leads)}")

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

    print(f"Persisted {total_persisted} to Supabase")


if __name__ == "__main__":
    asyncio.run(main())
