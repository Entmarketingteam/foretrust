#!/usr/bin/env python3
"""One-shot eCCLIX login + county picker probe (no proxy)."""
import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.browser import create_browser, human_delay
from app.connectors.residential import ecclix_portal as portal
from app.config import settings
from app.browser import safe_goto


async def main() -> None:
    county = (sys.argv[1] if len(sys.argv) > 1 else "scott").lower()
    user = os.environ.get("ECCLIX_USERNAME") or settings.ecclix_username
    pwd = os.environ.get("ECCLIX_PASSWORD") or settings.ecclix_password
    if not user or not pwd:
        print("MISSING ECCLIX_USERNAME / ECCLIX_PASSWORD in Doppler")
        return

    async with create_browser(headless=False) as browser:
        page = await browser.new_page()
        base = "https://www.ecclix.com"
        print("login...", flush=True)
        await portal.login(page, base, user, pwd)
        print("url after login:", page.url)
        print("is_login_page:", await portal.is_login_page(page))
        body = (await page.inner_text("body"))[:2000]
        print("body snippet:", body.replace("\n", " ")[:500])

        await safe_goto(page, f"{base}/ecclix/usercounties.aspx")
        await human_delay(2, 3)
        print("url counties:", page.url)
        links = await page.eval_on_selector_all(
            "a",
            "els => els.map(e => (e.innerText||'').trim()).filter(t => t.length > 2 && t.length < 80)",
        )
        search_links = [t for t in links if "search" in t.lower() and "record" in t.lower()]
        print("search links:", search_links[:20])

        ok = await portal.select_county_if_needed(page, county)
        print("select_county:", ok, "url:", page.url)
        print("session_established:", await portal.session_established(page))
        await human_delay(5, 5)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
