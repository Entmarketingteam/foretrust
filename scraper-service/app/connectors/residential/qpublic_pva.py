"""Schneider qPublic (Beacon) PVA base for Kentucky counties."""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Page

from app.connectors.residential.base_pva import BasePVAConnector
from app.browser import human_delay, safe_goto
from app.models import RawRecord
from app.pipeline.normalize import parse_currency, parse_int_commas
from app.pipeline.property_address import normalize_property_address

logger = logging.getLogger(__name__)

QPUBLIC_HOST = "https://qpublic.schneidercorp.com"

# Scott/Woodford/Madison qPublic ASP.NET control IDs
_ADDR_INPUT = "#ctlBodyPane_ctl03_ctl01_txtAddress"
_ADDR_SEARCH = "#ctlBodyPane_ctl03_ctl01_btnSearch"
_NAME_INPUT = "#ctlBodyPane_ctl02_ctl01_txtName"
_NAME_SEARCH = "#ctlBodyPane_ctl02_ctl01_btnSearch"
_PARCEL_INPUT = "#ctlBodyPane_ctl04_ctl01_txtParcelID"
_PARCEL_SEARCH = "#ctlBodyPane_ctl04_ctl01_btnSearch"


class QPublicPVAConnector(BasePVAConnector):
    """PVA connector for counties hosted on Schneider qPublic."""

    qpublic_app: str = ""

    @property
    def base_url(self) -> str:
        return QPUBLIC_HOST

    @property
    def search_path(self) -> str:
        app = self.qpublic_app or f"{self.county_name}CountyKY"
        return f"/Application.aspx?App={app}&PageType=Search"

    async def _wait_portal_ready(self, page: Page, timeout_sec: int = 60) -> bool:
        for i in range(max(1, timeout_sec // 2)):
            # Aggressively dismiss terms during wait
            await self._dismiss_terms(page)
            
            title = (await page.title() or "").lower()
            blocked = "just a moment" in title or "verify you are human" in title
            inp = await page.query_selector(_ADDR_INPUT)
            if inp and not blocked:
                return True
            
            if i % 5 == 0:
                logger.info("[%s] Waiting for qPublic... (Title: %s)", self.source_key, title)
            await human_delay(2.0, 3.0)
        
        await page.screenshot(path=f"debug_qpublic_fail_{self.source_key}.png")
        return False

    async def _dismiss_terms(self, page: Page) -> None:
        agree = await page.query_selector(
            ".modal-footer a.btn-primary, .modal a.button-1, "
            "button:has-text('Agree'), a:has-text('Agree')"
        )
        if agree:
            try:
                if await agree.is_visible():
                    await agree.click(timeout=5000)
                    await human_delay(0.5, 1.0)
            except Exception:
                pass

    async def _lookup(self, page: Page, query: str, search_by: str = "address") -> RawRecord | None:
        """qPublic-specific search (ASP.NET ctlBodyPane fields)."""
        from app.captcha import detect_and_solve_captcha

        search_url = f"{self.base_url}{self.search_path}"
        await safe_goto(page, search_url)
        await human_delay(1.0, 2.0)

        if not await self._wait_portal_ready(page):
            logger.warning("[%s] qPublic not ready", self.source_key)
            return None

        await self._dismiss_terms(page)

        try:
            await detect_and_solve_captcha(page)
        except Exception as exc:
            logger.debug("[%s] captcha: %s", self.source_key, exc)

        q = (query or "").strip()
        if search_by == "name":
            input_sel, btn_sel = _NAME_INPUT, _NAME_SEARCH
        elif search_by == "parcel" or re.match(r"^[\d\-./]+$", q):
            input_sel, btn_sel = _PARCEL_INPUT, _PARCEL_SEARCH
        else:
            input_sel, btn_sel = _ADDR_INPUT, _ADDR_SEARCH

        search_input = await page.query_selector(input_sel)
        if not search_input:
            logger.warning("[%s] qPublic search input missing: %s", self.source_key, input_sel)
            return None

        await search_input.fill("")
        await search_input.fill(q)
        await human_delay(0.5, 1.0)

        try:
            await page.locator(btn_sel).click(timeout=15000)
        except Exception as exc:
            logger.warning("[%s] search click failed, retry: %s", self.source_key, exc)
            await human_delay(1.0, 2.0)
            try:
                await page.locator(btn_sel).click(timeout=15000, force=True)
            except Exception:
                return None
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await human_delay(1.5, 2.5)

        # qPublic often jumps straight to parcel detail (PageTypeID=4)
        if "PageTypeID=4" not in page.url and "KeyValue=" not in page.url:
            detail_link = await page.query_selector(
                "a[href*='PageTypeID=4'], a[href*='KeyValue='], "
                ".search-results a, table tbody tr td a"
            )
            if detail_link:
                await detail_link.click()
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                await human_delay(1.5, 2.5)

        return await self._extract_full_record(page, q)

    async def _extract_full_record(self, page: Page, search_query: str) -> RawRecord | None:
        """Parse Schneider qPublic parcel detail layout (label/value rows)."""
        body = await page.inner_text("body")
        if "security verification" in body.lower() or "just a moment" in body.lower():
            return None

        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        data: dict[str, Any] = {
            "search_query": search_query,
            "county": self.county_name,
            "source": "qpublic_detail",
        }

        for i, line in enumerate(lines):
            low = line.lower()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if line == "Owner" and nxt and not nxt[0].isdigit():
                data["owner_name"] = nxt
            elif line == "Homestead":
                data["homestead_exemption"] = nxt
            elif line == "Living Sqft" and nxt:
                data["building_sqft"] = parse_int_commas(nxt)
            elif line == "Year Built" and re.match(r"^\d{4}$", nxt):
                data["year_built"] = int(nxt)
            elif "mailing" in low and "@" not in nxt and len(nxt) > 8:
                data["mailing_address"] = nxt

        # Site address — first line that looks like situs after property header
        for line in lines:
            clean = normalize_property_address(line)
            if clean:
                data["property_address"] = clean
                break

        m_parcel = re.search(r"KeyValue=([\d.\-]+)", page.url)
        if m_parcel:
            data["parcel_number"] = m_parcel.group(1)

        # Last sale (first row in sales table)
        sale_m = re.search(
            r"(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+\$?([\d,]+)",
            body,
        )
        if sale_m:
            data["last_sale_date"] = sale_m.group(1)
            data["last_sale_price"] = parse_currency(sale_m.group(2))
            yr = sale_m.group(1).split("/")[-1]
            if yr.isdigit():
                data["last_sale_year"] = int(yr)

        # Taxable assessment (2025 certified column — third $ in row after label)
        for i, line in enumerate(lines):
            if "Taxable Assessment Total" in line:
                for j in range(i + 1, min(i + 6, len(lines))):
                    val = parse_currency(lines[j])
                    if val:
                        data["assessed_value"] = val
                        break
                break

        if not data.get("owner_name") and not data.get("assessed_value"):
            # Fallback to generic Tyler selectors
            return await super()._extract_full_record(page, search_query)

        return RawRecord(source_key=self.source_key, data=data)
