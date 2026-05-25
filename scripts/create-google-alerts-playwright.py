#!/usr/bin/env python3
"""Create all Foretrust Google Alerts (RSS delivery) via Playwright.

First run opens Chromium — log into coachethanatchley@gmail.com once.
Session is saved to .google-alerts-browser-profile/ (gitignored).

  cd ~/Desktop/foretrust
  python3 scripts/create-google-alerts-playwright.py

On success, sets GOOGLE_ALERTS_RSS_URLS in Doppler foretrust-scraper prd+dev.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
QUERIES_FILE = ROOT / "config" / "google-alerts-queries.txt"
PROFILE = ROOT / ".google-alerts-browser-profile"
ALERTS = "https://www.google.com/alerts"


def load_queries() -> list[str]:
    return [
        ln.strip()
        for ln in QUERIES_FILE.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def doppler_set_rss(urls: list[str]) -> None:
    joined = ",".join(urls)
    for cfg in ("prd", "dev"):
        subprocess.run(
            [
                "doppler", "secrets", "set",
                f"GOOGLE_ALERTS_RSS_URLS={joined}",
                "--project", "foretrust-scraper",
                "--config", cfg,
            ],
            check=True,
        )
    print(f"Doppler updated (prd + dev) with {len(urls)} RSS URL(s).")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Run: pip3 install playwright && playwright install chromium")
        return 1

    queries = load_queries()
    PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            slow_mo=100,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(ALERTS, wait_until="domcontentloaded")
        time.sleep(2)

        if "accounts.google.com" in page.url or page.locator('input[type="email"]').count():
            print("\n>>> Log into Google in the browser window.")
            print(">>> When you see the Google Alerts search box, press ENTER in this terminal.\n")
            input()

        for i, query in enumerate(queries, 1):
            print(f"[{i}/{len(queries)}] {query}")
            page.goto(f"{ALERTS}?hl=en&q={quote_plus(query)}", wait_until="domcontentloaded")
            time.sleep(1.2)

            box = page.locator('input[aria-label="Search"], input[type="text"]').first
            try:
                box.fill(query, timeout=5000)
            except Exception:
                pass

            btn = page.get_by_role("button", name=re.compile(r"create alert", re.I))
            if btn.count() == 0:
                btn = page.locator("button").filter(has_text=re.compile(r"create alert", re.I))
            if btn.count() > 0:
                btn.first.click()
                time.sleep(1.5)
                print("  OK")
            else:
                print("  — click Create Alert manually if needed, then ENTER")
                input()

        page.goto(f"{ALERTS}#", wait_until="domcontentloaded")
        time.sleep(2)
        print("\nCollecting RSS links from alerts page...")
        feed_urls: list[str] = []
        for el in page.locator("a[href*='alerts/feeds']").all():
            href = el.get_attribute("href") or ""
            if href.startswith("http") and href not in feed_urls:
                feed_urls.append(href)

        html = page.content()
        for m in re.findall(r"https://www\.google\.com/alerts/feeds/\d+/\d+", html):
            if m not in feed_urls:
                feed_urls.append(m)

        context.close()

    if len(feed_urls) < len(queries):
        print(f"\nOnly found {len(feed_urls)} RSS URLs (expected ~{len(queries)}).")
        print("On https://www.google.com/alerts# open each alert → RSS icon → add URLs to Doppler.")
        for u in feed_urls:
            print(f"  {u}")
        if not feed_urls:
            return 1

    for u in feed_urls:
        print(u)
    doppler_set_rss(feed_urls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
