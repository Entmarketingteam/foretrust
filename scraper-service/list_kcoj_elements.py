import asyncio
import os
from app.browser import create_browser, safe_goto
from app.connectors.residential.kcoj_courtnet import KCOJCourtNetConnector

async def run_list():
    username = os.environ.get("KCOJ_USERNAME")
    password = os.environ.get("KCOJ_PASSWORD")
    
    async with create_browser(headless=True) as browser:
        page = await browser.new_page()
        connector = KCOJCourtNetConnector()
        
        await connector._ensure_session(page)
        await connector._expand_party_search_panel(page)
        await asyncio.sleep(2)
        
        print("\n--- ALL SELECT ELEMENTS ---")
        selects = await page.query_selector_all("select")
        for s in selects:
            sid = await s.get_attribute("id")
            sname = await s.get_attribute("name")
            sclass = await s.get_attribute("class")
            print(f"ID: '{sid}' | NAME: '{sname}' | CLASS: '{sclass}'")
            
        print("\n--- ALL INPUT ELEMENTS ---")
        inputs = await page.query_selector_all("input")
        for i in inputs:
            iid = await i.get_attribute("id")
            iname = await i.get_attribute("name")
            itype = await i.get_attribute("type")
            print(f"ID: '{iid}' | NAME: '{iname}' | TYPE: '{itype}'")
            
        await page.screenshot(path="kcoj_panel_debug.png")
        print("\nScreenshot saved as kcoj_panel_debug.png")

if __name__ == "__main__":
    asyncio.run(run_list())
