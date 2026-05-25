"""Aggressive Bourbon County Extraction with Logging.
"""

from __future__ import annotations
import asyncio
import os
import sys
from playwright.async_api import async_playwright
from app.browser import create_browser, safe_goto, human_type

async def run():
    username = os.environ.get("ECCLIX_USERNAME")
    password = os.environ.get("ECCLIX_PASSWORD")
    
    async with create_browser(headless=True) as browser:
        page = await browser.new_page()
        
        # 1. Login
        print("[Bourbon] Logging in...")
        await safe_goto(page, 'https://www.ecclix.com/ecclix/login.aspx')
        await page.fill("input[type='text']", username)
        await page.fill("input[type='password']", password)
        await page.click("#btnLogin")
        await page.wait_for_load_state('networkidle')
        
        if "Force" in await page.content():
            btn = await page.query_selector("input[value*='Force']")
            if btn: await btn.click()
            await page.wait_for_load_state('networkidle')
        
        # 2. Select Bourbon
        print("[Bourbon] Navigating to county selection...")
        await page.goto('https://www.ecclix.com/ecclix/usercounties.aspx')
        await page.wait_for_load_state('networkidle')
        
        # Try to find the Bourbon link
        links = await page.query_selector_all("a")
        found = False
        for l in links:
            text = await l.inner_text()
            if "BOURBON" in text.upper():
                print(f"[Bourbon] Clicking link: {text}")
                await l.click()
                await page.wait_for_load_state('networkidle')
                found = True
                break
        
        if not found:
            print("[Bourbon] Could not find link. Trying direct search page...")
            await page.goto('https://www.ecclix.com/ecclix/instrinq.aspx')
            await page.wait_for_load_state('networkidle')

        # 3. Search for LP
        print("[Bourbon] Searching for LP...")
        # Check if we can select LP
        try:
            await page.select_option("select[name*='uceType']", label="LP")
            await page.fill("input[name*='BeginningDate']", "01/01/2026")
            await page.click("input#Search, #ctl00_Content_gbSearch_btnSearch")
            await page.wait_for_load_state('networkidle')
            print("[Bourbon] Search submitted.")
            
            # Check results
            rows = await page.query_selector_all("tr")
            print(f"[Bourbon] Found {len(rows)} potential result rows.")
            
            # Save screenshot of results
            await page.screenshot(path='bourbon_results.png')
            
        except Exception as e:
            print(f"[Bourbon] LP Search failed: {e}")

if __name__ == "__main__":
    asyncio.run(run())
