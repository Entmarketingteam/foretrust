#!/usr/bin/env python3
"""Dump instrument type dropdown options after county select."""
import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.browser import create_browser, human_delay, safe_goto
from app.config import settings
from app.connectors.residential import ecclix_portal as portal


async def main() -> None:
    county = (sys.argv[1] if len(sys.argv) > 1 else "scott").lower()
    user = os.environ.get("ECCLIX_USERNAME") or settings.ecclix_username
    pwd = os.environ.get("ECCLIX_PASSWORD") or settings.ecclix_password
    base = "https://www.ecclix.com"

    async with create_browser() as browser:
        page = await browser.new_page()
        await portal.login(page, base, user, pwd)
        await portal.select_county_if_needed(page, county)
        await portal.goto_instrument_search(page, base)
        await human_delay(2, 3)
        print("url:", page.url)
        print("has form:", await portal._page_has_index_search_form(page))
        selects = await page.query_selector_all("select")
        print("select count:", len(selects))
        for i, sel in enumerate(selects):
            opts = await sel.evaluate(
                "el => Array.from(el.options).map(o => o.textContent.trim()).filter(Boolean)"
            )
            name = await sel.get_attribute("name") or await sel.get_attribute("id") or "?"
            print(f"select[{i}] name={name} ({len(opts)} opts):", opts[:40])
        # RadCombo / Telerik-style lists
        combos = await page.query_selector_all("[id*='Type' i], [id*='Instrument' i]")
        print("type-ish elements:", len(combos))
        for el in combos[:5]:
            tag = await el.evaluate("e => e.tagName")
            print(" ", tag, await el.get_attribute("id"), await el.get_attribute("class"))
        body = await page.inner_text("body")
        for line in body.split("\n"):
            t = line.strip()
            if t and ("type" in t.lower() or "instrument" in t.lower() or "between" in t.lower()):
                if len(t) < 120:
                    print("body:", t)
        for code in ("LP", "DEED", "MTG", "WILL", "JLIEN", "MLIEN", "SLIEN", "ENC", "REL"):
            ok = await portal._select_instrument_type(page, code)
            print(f"  select {code}: {ok}")


if __name__ == "__main__":
    asyncio.run(main())
