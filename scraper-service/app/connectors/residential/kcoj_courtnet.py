"""Kentucky Court of Justice (KCOJ) CourtNet 2.0 connector.

Scrapes probate, estate, divorce, and foreclosure (civil) case filings
from kcoj.kycourts.net/casesearch across configured KY counties.

Enhanced: clicks into each case to extract full detail —
  - All parties (plaintiff/defendant/respondent/petitioner) with roles
  - Attorney names for each party
  - Case status and disposition
  - Dollar amounts (foreclosure loan balance, judgment amount)
  - Any property address referenced in the case
  - Docket entry summary
"""

from __future__ import annotations

import logging
import re
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

# Counties to scrape by default — matches counties with GIS + PVA coverage
DEFAULT_COUNTIES = [
    "Fayette", "Scott", "Oldham", "Woodford", "Jessamine", "Clark", "Madison", "Jefferson",
]

# Keywords in civil cases that confirm property-related distress
FORECLOSURE_KEYWORDS = [
    "FORECLOS", "LIS PENDENS", "MORTGAGE", "LIEN", "DEED OF TRUST",
    "MASTER COMMISSIONER", "DEFAULT", "JUDICIAL SALE",
]

# Dollar amount patterns in case text
_AMOUNT_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")

# Street address pattern
_ADDR_RE = re.compile(
    r"\d{1,6}\s+[A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|"
    r"Road|Rd|Court|Ct|Way|Place|Pl|Pike|Circle|Cir)(?:\s+[A-Za-z]+)?",
    re.IGNORECASE,
)


@register
class KCOJCourtNetConnector(BaseConnector):
    source_key = "kcoj_courtnet"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://kcoj.kycourts.net"
    default_schedule = "0 6 * * *"
    respects_robots = False  # Public court records — KRS 61.872 mandates public access

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        counties = params.get("counties", DEFAULT_COUNTIES)
        case_types = params.get("case_types", list(CASE_TYPE_MAP.keys()))
        limit = params.get("limit", 50)
        # Set False to skip per-case detail scraping (faster but less data)
        deep_scrape = params.get("deep_scrape", True)

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for county in counties:
                for case_type in case_types:
                    try:
                        batch = await self._search_county_case_type(
                            page, county, case_type, limit, deep_scrape
                        )
                        records.extend(batch)
                    except Exception as exc:
                        logger.warning(
                            "[kcoj] Failed %s/%s: %s", county, case_type, exc
                        )
                    await human_delay(3.0, 6.0)

        return records

    async def _search_county_case_type(
        self, page, county: str, case_type: str, limit: int, deep_scrape: bool
    ) -> list[RawRecord]:
        await safe_goto(page, f"{self.base_url}/casesearch")
        await human_delay()

        await detect_and_solve_captcha(page)

        county_select = await page.query_selector("select#County, select[name='County']")
        if county_select:
            await page.select_option("select#County, select[name='County']", label=county)
            await human_delay(1.0, 2.0)

        case_select = await page.query_selector("select#CaseType, select[name='CaseType']")
        if case_select:
            await page.select_option("select#CaseType, select[name='CaseType']", label=case_type)
            await human_delay(1.0, 2.0)

        today = date.today()
        thirty_ago = today - timedelta(days=30)
        date_from = await page.query_selector("input#FiledDateFrom, input[name='FiledDateFrom']")
        if date_from:
            await date_from.fill(thirty_ago.strftime("%m/%d/%Y"))
        date_to = await page.query_selector("input#FiledDateTo, input[name='FiledDateTo']")
        if date_to:
            await date_to.fill(today.strftime("%m/%d/%Y"))

        search_btn = await page.query_selector(
            "input#Search, button[type='submit'], input[type='submit']"
        )
        if search_btn:
            await search_btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay()

        await detect_and_solve_captcha(page)

        records: list[RawRecord] = []
        rows = await page.query_selector_all(
            "tr.data-row, table.results tr:not(:first-child), .search-results tr"
        )

        for row in rows[:limit]:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                cell_texts = [
                    (await cell.inner_text()).strip() for cell in cells
                ]

                # Try to get the link to the case detail page
                link_el = await row.query_selector("a[href*='casesearch'], a[href*='case']")
                case_href = await link_el.get_attribute("href") if link_el else None

                base_data = {
                    "county": county,
                    "case_type": case_type,
                    "cells": cell_texts,
                    "name": cell_texts[0] if cell_texts else "",
                    "case_id": cell_texts[1] if len(cell_texts) > 1 else "",
                    "filed_date": cell_texts[2] if len(cell_texts) > 2 else "",
                    "case_description": cell_texts[3] if len(cell_texts) > 3 else "",
                    "case_status": cell_texts[4] if len(cell_texts) > 4 else "",
                }

                # Deep scrape: click into the case for full detail
                if deep_scrape and case_href:
                    try:
                        detail_url = (
                            case_href
                            if case_href.startswith("http")
                            else f"{self.base_url}{case_href}"
                        )
                        detail = await self._extract_case_detail(page, detail_url)
                        base_data.update(detail)
                        await page.go_back()
                        await human_delay(1.5, 3.0)
                    except Exception as exc:
                        logger.debug("[kcoj] Case detail failed for %s: %s", base_data.get("case_id"), exc)

                records.append(RawRecord(source_key=self.source_key, data=base_data))

            except Exception as exc:
                logger.debug("[kcoj] Row parse error: %s", exc)

        logger.info("[kcoj] %s/%s: %d records", county, case_type, len(records))
        return records

    async def _extract_case_detail(self, page, url: str) -> dict:
        """Navigate to a KCOJ case detail page and extract all available data.

        Returns a dict that gets merged into the base_data dict.
        """
        await safe_goto(page, url)
        await human_delay(1.5, 2.5)

        detail: dict[str, Any] = {}
        full_text = ""

        try:
            full_text = await page.inner_text("body")
        except Exception:
            pass

        # --- Case Header ---
        for selector, key in [
            (".case-number, #CaseNumber, [data-field='case_number']", "case_number_detail"),
            (".case-status, #CaseStatus, [data-field='case_status']", "case_status_detail"),
            (".judge-name, #JudgeName, [data-field='judge']", "judge_name"),
            (".court-name, #CourtName, [data-field='court']", "court_name"),
            (".disposition, #Disposition, [data-field='disposition']", "disposition"),
        ]:
            el = await page.query_selector(selector)
            if el:
                detail[key] = (await el.inner_text()).strip()

        # --- Parties Table ---
        # KCOJ typically has a parties section with: Name | Role | DOB | Attorney
        parties: list[dict] = []
        party_rows = await page.query_selector_all(
            ".parties-table tr:not(:first-child), "
            "table#PartiesTable tr:not(:first-child), "
            ".party-row"
        )
        for row in party_rows:
            cells = await row.query_selector_all("td")
            if len(cells) >= 2:
                party = {
                    "name": (await cells[0].inner_text()).strip() if cells else "",
                    "role": (await cells[1].inner_text()).strip() if len(cells) > 1 else "",
                    "dob": (await cells[2].inner_text()).strip() if len(cells) > 2 else "",
                    "attorney": (await cells[3].inner_text()).strip() if len(cells) > 3 else "",
                }
                if party["name"]:
                    parties.append(party)

        if parties:
            detail["all_parties"] = parties
            # Convenience fields
            plaintiffs = [p for p in parties if "PLAINTIFF" in p.get("role", "").upper()
                          or "PETITIONER" in p.get("role", "").upper()]
            defendants = [p for p in parties if "DEFENDANT" in p.get("role", "").upper()
                          or "RESPONDENT" in p.get("role", "").upper()]
            if plaintiffs:
                detail["plaintiff"] = plaintiffs[0]["name"]
                detail["plaintiff_attorney"] = plaintiffs[0].get("attorney", "")
            if defendants:
                detail["defendant"] = defendants[0]["name"]
                detail["defendant_attorney"] = defendants[0].get("attorney", "")

        # --- Dollar Amounts (foreclosure loan balance / judgment) ---
        amounts = _AMOUNT_RE.findall(full_text)
        if amounts:
            # Filter out small amounts (fees) — keep amounts > $10,000
            big_amounts = []
            for amt_str in amounts:
                try:
                    val = float(amt_str.replace("$", "").replace(",", ""))
                    if val >= 10_000:
                        big_amounts.append(val)
                except ValueError:
                    pass
            if big_amounts:
                detail["claim_amounts"] = big_amounts
                detail["max_claim_amount"] = max(big_amounts)

        # --- Property Address in Case Text ---
        addr_matches = _ADDR_RE.findall(full_text)
        if addr_matches:
            detail["property_address_in_case"] = addr_matches[0].strip()
            detail["all_addresses_in_case"] = [a.strip() for a in addr_matches[:5]]

        # --- Docket Entries (most recent 5) ---
        docket_rows = await page.query_selector_all(
            ".docket-table tr:not(:first-child), "
            "table#DocketTable tr:not(:first-child), "
            ".docket-entry"
        )
        docket_entries = []
        for row in docket_rows[:5]:
            text = (await row.inner_text()).strip()
            if text:
                docket_entries.append(text)
        if docket_entries:
            detail["docket_entries"] = docket_entries

        # --- Master Commissioner Sale Date (if scheduled) ---
        mc_match = re.search(
            r"(?:master commissioner|mc sale|commissioner.*sale)[^\n]*?(\d{1,2}/\d{1,2}/\d{4})",
            full_text, re.IGNORECASE,
        )
        if mc_match:
            detail["mc_sale_date"] = mc_match.group(1)

        return detail

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        case_type = data.get("case_type", "")
        lead_type = CASE_TYPE_MAP.get(case_type, LeadType.PROBATE)

        # For civil cases, confirm property-related via keywords
        if lead_type == LeadType.FORECLOSURE:
            desc = (data.get("case_description") or "").upper()
            full_text = " ".join(str(v) for v in data.values()).upper()
            if not any(kw in full_text for kw in FORECLOSURE_KEYWORDS):
                lead_type = LeadType.ESTATE

        # Sub-classify probate
        if lead_type == LeadType.PROBATE:
            desc = (data.get("case_description") or "").upper()
            if any(kw in desc for kw in ["TRUST", "ESTATE OF", "ADMIN"]):
                lead_type = LeadType.ESTATE

        county = data.get("county", "")
        filed_date = parse_date(data.get("filed_date", ""))

        # Property address: prefer address found in the case text
        property_address = data.get("property_address_in_case") or None

        # Owner name: for probate/estate, use the estate/deceased name;
        # for foreclosure, use the defendant (borrower)
        if lead_type in (LeadType.FORECLOSURE, LeadType.PRE_FORECLOSURE):
            owner_name = data.get("defendant") or data.get("name")
        else:
            owner_name = data.get("name")

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county}",
            lead_type=lead_type,
            owner_name=owner_name,
            property_address=property_address,
            case_id=data.get("case_id"),
            case_filed_date=filed_date,
            state="KY",
            raw_payload=data,
        )
