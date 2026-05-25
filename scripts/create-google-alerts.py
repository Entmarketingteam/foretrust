#!/usr/bin/env python3
"""Create Foretrust Google Alerts and print RSS feed URLs for Doppler.

Requires: playwright (`pip install playwright` && `playwright install chromium`)
Run headed so you can log into Google once:

  cd ~/Desktop/foretrust
  python3 scripts/create-google-alerts.py

After completion, copy the printed doppler command (or it can auto-set if DOPPLER_AUTO=1).
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

QUERIES_FILE = Path(__file__).resolve().parent.parent / "config" / "google-alerts-queries.txt"
ALERTS_HOME = "https://www.google.com/alerts"
ALERTS_MANAGE = "https://www.google.com/alerts#"


def load_queries() -> list[str]:
    lines = QUERIES_FILE.read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install playwright: pip install playwright && playwright install chromium")
        return 1

    queries = load_queries()
    if not queries:
        print(f"No queries in {QUERIES_FILE}")
        return 1

    print(f"Will create {len(queries)} alerts from {QUERIES_FILE.name}")
    print("Log into Google (coachethanatchley@gmail.com) when the browser opens.\n")

    feed_urls: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=80)
        context = browser.new_context()
        page = context.new_page()

        page.goto(ALERTS_HOME, wait_until="domcontentloaded")
        print(">>> Sign in to Google if prompted, then press ENTER here...")
        input()

        for i, query in enumerate(queries, 1):
            print(f"\n[{i}/{len(queries)}] Creating: {query}")
            page.goto(ALERTS_HOME, wait_until="domcontentloaded")
            time.sleep(1.5)

            # Search box
            box = page.locator('input[type="text"]').first
            box.click()
            box.fill("")
            box.fill(query)
            time.sleep(0.8)

            # Create alert
            create = page.get_by_role("button", name=re.compile(r"create alert", re.I))
            if create.count() == 0:
                create = page.locator("button").filter(has_text=re.compile(r"create alert", re.I))
            if create.count() > 0:
                create.first.click()
                time.sleep(2.0)
                print("  Created (or updated).")
            else:
                print("  WARNING: Create Alert button not found — create this one manually.")

        print("\n>>> Opening manage page to collect RSS links...")
        page.goto(ALERTS_MANAGE, wait_until="domcontentloaded")
        time.sleep(2)
        print(">>> On the alerts list, click each alert's RSS/feed icon if visible.")
        print(">>> Press ENTER when done (or after 60s we'll scrape page for feed links)...")
        input()

        html = page.content()
        # RSS links in alerts UI
        for match in re.findall(
            r"https://www\.google\.com/alerts/feeds/[0-9]+/[0-9]+", html
        ):
            if match not in feed_urls:
                feed_urls.append(match)

        # Also check anchor hrefs via DOM
        for el in page.locator("a[href*='alerts/feeds']").all():
            href = el.get_attribute("href")
            if href and href not in feed_urls:
                feed_urls.append(href)

        browser.close()

    if not feed_urls:
        print("\nNo RSS URLs detected automatically.")
        print("Manual: open https://www.google.com/alerts# → each alert → RSS icon → copy URL")
        print("Then: doppler secrets set GOOGLE_ALERTS_RSS_URLS=\"url1,url2,...\" --project foretrust-scraper --config prd")
        return 1

    print(f"\nFound {len(feed_urls)} RSS feed URL(s):")
    for u in feed_urls:
        print(f"  {u}")

    joined = ",".join(feed_urls)
    cmd = (
        f'doppler secrets set GOOGLE_ALERTS_RSS_URLS="{joined}" '
        f"--project foretrust-scraper --config prd"
    )
    print(f"\nRun:\n  {cmd}\n")

    if os.environ.get("DOPPLER_AUTO") == "1":
        import subprocess
        subprocess.run(cmd, shell=True, check=True)
        print("Doppler updated (prd).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
