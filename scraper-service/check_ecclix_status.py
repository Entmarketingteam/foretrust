import asyncio
from app.browser import create_browser, safe_goto

async def run():
    async with create_browser(headless=True) as b:
        page = await b.new_page()
        # 1. Try to hit a county selection page
        print("Checking eCCLIX availability...")
        await safe_goto(page, 'https://www.ecclix.com/ecclix/usercounties.aspx')
        print(f"Current URL: {page.url}")
        
        content = await page.content()
        if "Login" in content or "login.aspx" in page.url:
            print("❌ Access blocked - redirected to login.")
        elif "Purchase" in content or "Subscribe" in content:
            print("⚠️ County selection visible but purchase required.")
        else:
            print("✅ Access might be active!")
            
        await page.screenshot(path='ecclix_status_check.png')
        print("Screenshot saved to ecclix_status_check.png")

if __name__ == "__main__":
    asyncio.run(run())
