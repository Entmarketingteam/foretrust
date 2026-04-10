"""Scott County PVA connector (eCCLIX-based).

Uses Playwright + pytesseract OCR for owner info trapped in images.
Detects: vacancy, tax_lien.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto

logger = logging.getLogger(__name__)


@register
class ScottPVAConnector(BaseConnector):
    source_key = "scott_pva"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Scott"
    base_url = "https://scottkypva.com"
    default_schedule = "0 7 * * *"
    respects_robots = True

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        search_addresses = params.get("addresses", [])
        limit = params.get("limit", 50)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            await safe_goto(page, self.base_url)
            await human_delay()

            if search_addresses:
                for addr in search_addresses[:limit]:
                    try:
                        record = await self._search_address(page, addr)
                        if record:
                            records.append(record)
                    except Exception as exc:
                        logger.warning("[scott_pva] Lookup failed for %s: %s", addr, exc)
                    await human_delay(2.0, 4.0)
            else:
                # Browse available property listings
                records = await self._browse_properties(page, limit)

        return records

    async def _search_address(self, page, address: str) -> RawRecord | None:
        """Search Scott PVA by address and extract data, using OCR if needed."""
        await safe_goto(page, self.base_url)
        await human_delay()

        search_input = await page.query_selector(
            "input#search, input[name='search'], input[type='text'], input#address"
        )
        if search_input:
            await search_input.fill(address)
            await human_delay(1.0, 2.0)

            submit = await page.query_selector(
                "button[type='submit'], input[type='submit'], .search-button"
            )
            if submit:
                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay()

        # Click Assessment tab if present
        assessment_tab = await page.query_selector(
            "a:has-text('Assessment'), button:has-text('Assessment'), .tab-assessment"
        )
        if assessment_tab:
            await assessment_tab.click()
            await human_delay()

        return await self._extract_with_ocr_fallback(page, address)

    async def _browse_properties(self, page, limit: int) -> list[RawRecord]:
        """Browse property listing pages."""
        records: list[RawRecord] = []

        # Look for property table rows
        rows = await page.query_selector_all(
            "table tr:not(:first-child), .property-row, .result-item"
        )

        for row in rows[:limit]:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                cell_texts = []
                for cell in cells:
                    text = (await cell.inner_text()).strip()
                    cell_texts.append(text)

                records.append(RawRecord(
                    source_key=self.source_key,
                    data={
                        "cells": cell_texts,
                        "owner_name": cell_texts[0] if cell_texts else "",
                        "property_address": cell_texts[1] if len(cell_texts) > 1 else "",
                        "assessed_value": cell_texts[2] if len(cell_texts) > 2 else "",
                    },
                ))
            except Exception as exc:
                logger.debug("[scott_pva] Row parse error: %s", exc)

        return records

    async def _extract_with_ocr_fallback(self, page, search_addr: str) -> RawRecord | None:
        """Extract property data, falling back to OCR for image-trapped text."""
        data: dict[str, Any] = {"property_address": search_addr, "source": "pva_search"}

        # Try direct text extraction first
        owner_el = await page.query_selector(
            ".owner-name, [data-field='owner'], td:has-text('Owner') + td"
        )
        if owner_el:
            data["owner_name"] = (await owner_el.inner_text()).strip()

        sqft_el = await page.query_selector(
            "[data-field='sqft'], td:has-text('Square') + td, td:has-text('Sq Ft') + td"
        )
        if sqft_el:
            text = (await sqft_el.inner_text()).strip()
            try:
                data["building_sqft"] = int(text.replace(",", ""))
            except ValueError:
                pass

        # If owner name is missing, try OCR on the owner info area
        if not data.get("owner_name"):
            try:
                owner_section = await page.query_selector(
                    ".owner-info, .property-owner, #ownerInfo, .assessment-owner"
                )
                if owner_section:
                    screenshot_bytes = await owner_section.screenshot()
                    data["owner_name"] = self._ocr_extract(screenshot_bytes)
                    data["ocr_used"] = True
            except Exception as exc:
                logger.warning("[scott_pva] OCR fallback failed: %s", exc)

        if not data.get("owner_name") and not data.get("property_address"):
            return None

        return RawRecord(source_key=self.source_key, data=data)

    @staticmethod
    def _ocr_extract(image_bytes: bytes) -> str:
        """Use pytesseract to read text from a screenshot."""
        try:
            import pytesseract
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img).strip()
            # Take the first non-empty line as the owner name
            for line in text.split("\n"):
                line = line.strip()
                if line and len(line) > 2:
                    return line
        except ImportError:
            logger.warning("pytesseract not available; OCR disabled")
        except Exception as exc:
            logger.warning("OCR extraction failed: %s", exc)
        return ""

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        sqft = data.get("building_sqft")
        assessed = data.get("assessed_value")

        lead_type = LeadType.VACANCY
        if "DELINQ" in str(data).upper() or "TAX" in str(data).upper():
            lead_type = LeadType.TAX_LIEN

        estimated = None
        if assessed:
            try:
                estimated = float(str(assessed).replace(",", "").replace("$", ""))
            except ValueError:
                pass

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction="KY-Scott",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            city="GEORGETOWN",
            state="KY",
            building_sqft=sqft if isinstance(sqft, int) else None,
            estimated_value=estimated,
            raw_payload=data,
        )
