"""Kentucky Master Commissioner foreclosure sale monitor.

In Kentucky all foreclosures are judicial — the circuit court appoints a
Master Commissioner who conducts the public auction. Sales are advertised
3 weeks in advance in the local newspaper AND posted on the circuit court's
website (via KCOJ).

This connector monitors two sources:
  1. The KCOJ Master Commissioner listing page (circuit court postings)
  2. The individual county circuit court MC pages for target counties

What we extract per sale listing:
  - Property address (the thing being auctioned)
  - Case number (links back to KCOJ court case)
  - Sale date + time + location
  - Opening bid / minimum bid
  - Plaintiff (lender/bank foreclosing)
  - Defendant (current owner — our target)
  - Attorney for plaintiff
  - Legal description / parcel number

WHY this matters:
  A Master Commissioner sale is the final stage of foreclosure. The sale
  date is known in advance. Properties often sell below market. The owner
  has exhausted all options. This is the highest-urgency distress signal.

KCOJ MC page: https://kcoj.kycourts.net/mastercommissioner/
(Individual county circuit court sites are scraped as fallbacks)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto
from app.pipeline.normalize import parse_date

logger = logging.getLogger(__name__)

# Counties to monitor for MC sales
DEFAULT_MC_COUNTIES = [
    "Fayette", "Scott", "Oldham", "Woodford", "Jessamine",
    "Clark", "Madison", "Jefferson",
]

# Dollar amount pattern
_AMOUNT_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")

# Date pattern: "January 15, 2025" or "01/15/2025"
_DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{4}",
    re.IGNORECASE,
)

# Street address pattern
_ADDR_RE = re.compile(
    r"\d{1,6}\s+[A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|"
    r"Road|Rd|Court|Ct|Way|Place|Pl|Pike|Circle|Cir)(?:\s+[A-Za-z]+)?",
    re.IGNORECASE,
)


@register
class KYMasterCommissionerConnector(BaseConnector):
    source_key = "ky_master_commissioner"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://kcoj.kycourts.net"
    default_schedule = "0 7 * * 1,3,5"  # Mon/Wed/Fri — sales typically posted M-F
    respects_robots = False  # Public court records — KRS 61.872

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        counties = params.get("counties", DEFAULT_MC_COUNTIES)
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            # Source 1: KCOJ Master Commissioner portal
            try:
                mc_records = await self._scrape_kcoj_mc_portal(page, counties, limit)
                records.extend(mc_records)
                logger.info("[mc] KCOJ portal: %d records", len(mc_records))
            except Exception as exc:
                logger.warning("[mc] KCOJ MC portal failed: %s", exc)

            # Source 2: Individual county MC pages (fallback / supplemental)
            for county in counties:
                try:
                    county_records = await self._scrape_county_mc_page(page, county, limit)
                    records.extend(county_records)
                except Exception as exc:
                    logger.debug("[mc] County page failed for %s: %s", county, exc)
                await human_delay(2.0, 4.0)

        logger.info("[mc] Total MC sale records: %d", len(records))
        return records

    async def _scrape_kcoj_mc_portal(
        self, page, counties: list[str], limit: int
    ) -> list[RawRecord]:
        """Scrape the KCOJ Master Commissioner listings page."""
        mc_url = f"{self.base_url}/mastercommissioner/"
        await safe_goto(page, mc_url)
        await human_delay(2.0, 3.5)

        records: list[RawRecord] = []

        # Try to filter by county
        county_select = await page.query_selector("select#County, select[name='county']")
        for county in counties:
            try:
                if county_select:
                    await page.select_option(
                        "select#County, select[name='county']", label=county
                    )
                    await human_delay(1.0, 2.0)
                    search_btn = await page.query_selector(
                        "button[type='submit'], input[type='submit']"
                    )
                    if search_btn:
                        await search_btn.click()
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await human_delay()

                county_records = await self._extract_mc_listings(page, county)
                records.extend(county_records)
            except Exception as exc:
                logger.debug("[mc] County filter failed for %s: %s", county, exc)

        # If no county filter: parse all listings on the page
        if not records:
            all_records = await self._extract_mc_listings(page, "unknown")
            records.extend(all_records[:limit])

        return records[:limit]

    async def _extract_mc_listings(self, page, county: str) -> list[RawRecord]:
        """Parse MC sale listings from the current page."""
        records: list[RawRecord] = []

        # MC listings may be in a table or as individual divs
        rows = await page.query_selector_all(
            "table.mc-listings tr:not(:first-child), "
            ".mc-listing-row, .sale-listing, "
            "table.results tr:not(:first-child)"
        )

        for row in rows:
            try:
                text = (await row.inner_text()).strip()
                if not text or len(text) < 20:
                    continue

                data = await self._parse_mc_text(text, county)
                if data:
                    records.append(RawRecord(source_key=self.source_key, data=data))
            except Exception as exc:
                logger.debug("[mc] Listing parse error: %s", exc)

        # If no rows found, try parsing the full page text into sale blocks
        if not records:
            full_text = await page.inner_text("main, .content, body")
            records = self._parse_mc_full_text(full_text, county)

        return records

    async def _scrape_county_mc_page(
        self, page, county: str, limit: int
    ) -> list[RawRecord]:
        """Fallback: attempt to find MC listings on county circuit court websites.

        KY circuit courts sometimes post MC sales independently.
        URL patterns vary — this tries common patterns.
        """
        county_lower = county.lower()
        candidate_urls = [
            f"https://{county_lower}circuitcourt.ky.gov/mastercommissioner",
            f"https://{county_lower}.ky.gov/mastercommissioner",
            f"https://courts.ky.gov/{county_lower}/mastercommissioner",
        ]

        for url in candidate_urls:
            try:
                await safe_goto(page, url)
                await human_delay(2.0, 3.0)

                # Check if we got a valid page (not 404)
                title = await page.title()
                if "404" in title or "not found" in title.lower():
                    continue

                full_text = await page.inner_text("body")
                if "commissioner" in full_text.lower() or "sale" in full_text.lower():
                    records = self._parse_mc_full_text(full_text, county)
                    if records:
                        return records[:limit]
            except Exception:
                continue

        return []

    async def _parse_mc_text(self, text: str, county: str) -> dict | None:
        """Parse a single MC listing row/block into a structured dict."""
        data: dict[str, Any] = {
            "county": county,
            "source": "mc_listing",
            "raw_text": text[:2000],
        }

        # Extract address
        addr_match = _ADDR_RE.search(text)
        if addr_match:
            data["property_address"] = addr_match.group(0).strip()

        # Extract dates
        dates = _DATE_RE.findall(text)
        if dates:
            data["sale_date_text"] = dates[0]
            data["sale_date"] = parse_date(dates[0]) or parse_date(
                # Try numeric format
                next((d for d in dates if "/" in d), dates[0])
            )

        # Extract dollar amounts (opening bid)
        amounts = _AMOUNT_RE.findall(text)
        if amounts:
            parsed = []
            for amt in amounts:
                try:
                    val = float(amt.replace("$", "").replace(",", ""))
                    parsed.append(val)
                except ValueError:
                    pass
            if parsed:
                data["opening_bid"] = min(parsed)  # Smallest = opening bid
                data["all_amounts"] = parsed

        # Extract case number pattern (e.g. 24-CI-00123)
        case_match = re.search(r"\d{2,4}-[A-Z]{1,2}-\d{3,6}", text)
        if case_match:
            data["case_id"] = case_match.group(0)

        # Extract parties from "vs." or "v." pattern
        vs_match = re.search(
            r"([A-Z][A-Za-z\s,\.]+?)\s+(?:vs?\.)\s+([A-Z][A-Za-z\s,\.]+?)(?:\n|\.|$)",
            text, re.IGNORECASE,
        )
        if vs_match:
            data["plaintiff"] = vs_match.group(1).strip()
            data["defendant"] = vs_match.group(2).strip()

        # Must have at least an address or case number to be useful
        if not data.get("property_address") and not data.get("case_id"):
            return None

        return data

    def _parse_mc_full_text(self, text: str, county: str) -> list[RawRecord]:
        """Parse a full page of MC listings by splitting on case boundaries."""
        records: list[RawRecord] = []

        # Split on case number boundaries or "NOTICE OF SALE" / "COMMISSIONER SALE"
        blocks = re.split(
            r"(?:NOTICE OF SALE|COMMISSIONER.{0,20}SALE|CASE NO\.|\d{2,4}-CI-)",
            text, flags=re.IGNORECASE,
        )

        for block in blocks[1:]:  # Skip first (header) block
            block = block.strip()
            if len(block) < 30:
                continue
            import asyncio
            # Can't await in sync context — use a sync parse approach
            data: dict[str, Any] = {
                "county": county,
                "source": "mc_page_parse",
                "raw_text": block[:2000],
            }

            addr_match = _ADDR_RE.search(block)
            if addr_match:
                data["property_address"] = addr_match.group(0).strip()

            dates = _DATE_RE.findall(block)
            if dates:
                data["sale_date_text"] = dates[0]

            amounts = _AMOUNT_RE.findall(block)
            if amounts:
                parsed_amounts = []
                for amt in amounts:
                    try:
                        parsed_amounts.append(float(amt.replace("$", "").replace(",", "")))
                    except ValueError:
                        pass
                if parsed_amounts:
                    data["opening_bid"] = min(parsed_amounts)

            case_match = re.search(r"\d{2,4}-[A-Z]{1,2}-\d{3,6}", block)
            if case_match:
                data["case_id"] = case_match.group(0)

            if data.get("property_address") or data.get("case_id"):
                records.append(RawRecord(source_key=self.source_key, data=data))

        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        county = data.get("county", "")

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county}" if county else "KY-Multi",
            lead_type=LeadType.FORECLOSURE,
            owner_name=data.get("defendant"),
            property_address=data.get("property_address"),
            case_id=data.get("case_id"),
            case_filed_date=data.get("sale_date"),
            state="KY",
            estimated_value=data.get("opening_bid"),
            raw_payload=data,
        )
