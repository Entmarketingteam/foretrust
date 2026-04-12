"""Kentucky Court of Justice (KCOJ) CourtNet 2.0 connector.

Scrapes probate, estate, divorce, and foreclosure (civil) case filings
from kcoj.kycourts.net/casesearch across configured KY counties.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto
from app.captcha import detect_and_solve_captcha
from app.pipeline.normalize import parse_date

logger = logging.getLogger(__name__)

# KCOJ case-type prefixes → our LeadType
CASE_TYPE_MAP = {
    "P - Probate": LeadType.PROBATE,
    "D - Domestic Relations": LeadType.DIVORCE,
    "DR - Domestic Relations": LeadType.DIVORCE,
    "CI - Civil": LeadType.FORECLOSURE,
}

# Counties to scrape by default
DEFAULT_COUNTIES = ["Fayette", "Scott", "Oldham", "Woodford", "Jessamine", "Clark", "Madison"]


@register
class KCOJCourtNetConnector(BaseConnector):
    source_key = "kcoj_courtnet"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://kcoj.kycourts.net"
    default_schedule = "0 6 * * *"
    respects_robots = False  # Public court records — KRS 61.872 mandates public access; robots.txt is advisory

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        counties = params.get("counties", DEFAULT_COUNTIES)
        case_types = params.get("case_types", list(CASE_TYPE_MAP.keys()))
        limit = params.get("limit", 50)

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for county in counties:
                for case_type in case_types:
                    try:
                        batch = await self._search_county_case_type(
                            page, county, case_type, limit
                        )
                        records.extend(batch)
                    except Exception as exc:
                        logger.warning(
                            "[kcoj] Failed %s/%s: %s", county, case_type, exc
                        )
                    await human_delay(3.0, 6.0)

        return records

    async def _search_county_case_type(
        self, page, county: str, case_type: str, limit: int
    ) -> list[RawRecord]:
        await safe_goto(page, f"{self.base_url}/casesearch")
        await human_delay()

        # Handle CAPTCHA if present
        await detect_and_solve_captcha(page)

        # Select county
        county_select = await page.query_selector("select#County, select[name='County']")
        if county_select:
            await page.select_option("select#County, select[name='County']", label=county)
            await human_delay(1.0, 2.0)

        # Select case type
        case_select = await page.query_selector("select#CaseType, select[name='CaseType']")
        if case_select:
            await page.select_option("select#CaseType, select[name='CaseType']", label=case_type)
            await human_delay(1.0, 2.0)

        # Set date range: last 30 days
        today = date.today()
        thirty_ago = today - timedelta(days=30)
        date_from = await page.query_selector("input#FiledDateFrom, input[name='FiledDateFrom']")
        if date_from:
            await date_from.fill(thirty_ago.strftime("%m/%d/%Y"))
        date_to = await page.query_selector("input#FiledDateTo, input[name='FiledDateTo']")
        if date_to:
            await date_to.fill(today.strftime("%m/%d/%Y"))

        # Click search
        search_btn = await page.query_selector("input#Search, button[type='submit'], input[type='submit']")
        if search_btn:
            await search_btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay()

        # Handle CAPTCHA on results page
        await detect_and_solve_captcha(page)

        # Extract results
        records: list[RawRecord] = []
        rows = await page.query_selector_all("tr.data-row, table.results tr:not(:first-child), .search-results tr")

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
                        "county": county,
                        "case_type": case_type,
                        "cells": cell_texts,
                        "name": cell_texts[0] if cell_texts else "",
                        "case_id": cell_texts[1] if len(cell_texts) > 1 else "",
                        "filed_date": cell_texts[2] if len(cell_texts) > 2 else "",
                        "case_description": cell_texts[3] if len(cell_texts) > 3 else "",
                    },
                ))
            except Exception as exc:
                logger.debug("[kcoj] Row parse error: %s", exc)

        logger.info("[kcoj] %s/%s: %d records", county, case_type, len(records))
        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        case_type = data.get("case_type", "")
        lead_type = CASE_TYPE_MAP.get(case_type, LeadType.PROBATE)

        # For civil cases, classify as foreclosure only if keywords match
        if lead_type == LeadType.FORECLOSURE:
            desc = (data.get("case_description") or "").upper()
            if not any(kw in desc for kw in ["FORECLOS", "LIS PENDENS", "MORTGAGE", "LIEN"]):
                # Not property-related civil case, skip by marking as estate
                lead_type = LeadType.ESTATE

        # Sub-classify probate into probate vs estate
        if lead_type == LeadType.PROBATE:
            desc = (data.get("case_description") or "").upper()
            if any(kw in desc for kw in ["TRUST", "ESTATE OF", "ADMIN"]):
                lead_type = LeadType.ESTATE

        county = data.get("county", "")
        filed_date = parse_date(data.get("filed_date", ""))

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county}",
            lead_type=lead_type,
            owner_name=data.get("name"),
            case_id=data.get("case_id"),
            case_filed_date=filed_date,
            state="KY",
            raw_payload=data,
        )
