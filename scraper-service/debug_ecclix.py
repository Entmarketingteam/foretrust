import asyncio
import os
from app.browser import create_browser, safe_goto

async def run():
    username = os.environ.get("ECCLIX_USERNAME")
    password = os.environ.get("ECCLIX_PASSWORD")
    
    async with create_browser(headless=True) as browser:
        page = await browser.new_page()
        await safe_goto(page, 'https://www.ecclix.com/ecclix/login.aspx')
        
        # Check login fields
        user_f = await page.query_selector("input#txtUsername, input[type='text']")
        if user_f:
            await user_f.fill(username)
            await page.fill("input#txtPassword, input[type='password']", password)
            await page.click("#btnLogin, input[type='submit']")
            await page.wait_for_load_state('networkidle')
            
            if "Force" in await page.content():
                btn = await page.query_selector("input[value*='Force']")
                if btn: await btn.click()
                await page.wait_for_load_state('networkidle')

        await page.goto('https://www.ecclix.com/ecclix/instrinq.aspx')
        await page.wait_for_load_state('networkidle')
        
        print("--- FULL PAGE CONTENT ---")
        print(await page.content())
        print("--- END PAGE CONTENT ---")

if __name__ == "__main__":
    asyncio.run(run())
