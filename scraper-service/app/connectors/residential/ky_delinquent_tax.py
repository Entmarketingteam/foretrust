"""Kentucky county delinquent tax list monitor.

WHY this is the highest-distress signal:
  - KRS 134.128 requires counties to publish annual delinquent tax lists.
  - A property with 2+ years of unpaid taxes is at serious risk of tax sale.
  - Owner is often absent, deceased, or financially distressed.
  - No mortgage means free-and-clear ownership → motivated to avoid tax sale.
  - The list is public by law and updated annually (typically Jan-March).

Sources:
  1. County PVA websites (primary) — many post delinquent lists as searchable tables
  2. County Sheriff's Office — KRS 134.500 requires sheriff to publish delinquent list
  3. Local newspaper (backup) — legal notice requirement under KRS 134.128

What we extract per record:
  - Owner name + parcel number
  - Property address
  - Total taxes owed (principal + interest + penalty)
  - Years delinquent
  - Tax bill breakdown (state / county / city / school)
  - Any prior year liens

SCORING: Tax delinquency stacked with another signal (probate, divorce, vacancy)
generates the highest hot_scores in the system.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto
from app.pipeline.normalize import parse_currency, parse_int_commas

logger = logging.getLogger(__name__)

# Dollar amount pattern
_AMOUNT_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?|\d{1,3}(?:,\d{3})*(?:\.\d{2})?")

# County delinquent tax list URLs
# Each entry: county_name → (primary_url, fallback_url)
DELINQUENT_TAX_URLS: dict[str, dict] = {
    "fayette": {
        "primary": "https://fayettepva.com/delinquent-tax",
        "fallback": "https://fayettepva.com/property-search",
        "search_param": "delinquent=true",
        "city": "LEXINGTON",
    },
    "scott": {
        "primary": "https://scottkypva.com/delinquent",
        "fallback": "https://scottkypva.com",
        "city": "GEORGETOWN",
    },
    "oldham": {
        "primary": "https://oldhamcountypva.com/delinquent",
        "fallback": "https://oldhamcountypva.com",
        "city": "LA GRANGE",
    },
    "clark": {
        "primary": "https://clarkcountypva.com/delinquent",
        "fallback": "https://clarkcountypva.com",
        "city": "WINCHESTER",
    },
    "madison": {
        "primary": "https://madisoncountypva.com/delinquent",
        "fallback": "https://madisoncountypva.com",
        "city": "RICHMOND",
    },
    "woodford": {
        "primary": "https://woodfordpva.com/delinquent",
        "fallback": "https://woodfordpva.com",
        "city": "VERSAILLES",
    },
    "jessamine": {
        "primary": "https://jessaminepva.com/delinquent",
        "fallback": "https://jessaminepva.com",
        "city": "NICHOLASVILLE",
    },
    "jefferson": {
        "primary": "https://www.jeffersonpva.ky.gov/delinquent-tax/",
        "fallback": "https://www.jeffersonpva.ky.gov/property-search/",
        "city": "LOUISVILLE",
    },
}

# Keywords that confirm we're looking at a delinquent list
_DELINQUENT_MARKERS = [
    "DELINQUENT", "PAST DUE", "UNPAID", "OWING", "TAXES DUE",
    "PROPERTY TAX DELINQUENCY", "TAX LIEN",
]


@register
class KYDelinquentTaxConnector(BaseConnector):
    source_key = "ky_delinquent_tax"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://fayettepva.com"
    default_schedule = "0 9 * * 1"  # Weekly Monday — lists update infrequently
    respects_robots = False  # Public records mandated by KRS 134.128

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        counties = params.get("counties", list(DELINQUENT_TAX_URLS.keys()))
        limit = params.get("limit", 200)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for county in counties:
                cfg = DELINQUENT_TAX_URLS.get(county.lower())
                if not cfg:
                    logger.debug("[delinquent_tax] No URL config for %s", county)
                    continue

                try:
                    county_records = await self._scrape_county(page, county, cfg, limit)
                    records.extend(county_records)
                    logger.info(
                        "[delinquent_tax] %s: %d delinquent records", county, len(county_records)
                    )
                except Exception as exc:
                    logger.warning("[delinquent_tax] Failed for %s: %s", county, exc)
                await human_delay(3.0, 6.0)

        return records

    async def _scrape_county(
        self, page, county: str, cfg: dict, limit: int
    ) -> list[RawRecord]:
        """Scrape delinquent tax records for one county."""
        primary_url = cfg["primary"]
        city = cfg.get("city", "")

        # Try primary URL
        await safe_goto(page, primary_url)
        await human_delay(2.0, 3.5)

        page_text = ""
        try:
            page_text = await page.inner_text("body")
        except Exception:
            pass

        # Check if this page has delinquent content
        if not any(marker in page_text.upper() for marker in _DELINQUENT_MARKERS):
            # Try fallback: look for a "delinquent" link on the main PVA site
            fallback_url = cfg.get("fallback")
            if fallback_url:
                await safe_goto(page, fallback_url)
                await human_delay(2.0, 3.0)

                delinq_link = await page.query_selector(
                    "a:has-text('Delinquent'), a:has-text('delinquent'), "
                    "a:has-text('Tax Lien'), a:has-text('Unpaid Tax')"
                )
                if delinq_link:
                    await delinq_link.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await human_delay(2.0, 3.0)
                    page_text = await page.inner_text("body")

        # Extract records from the page
        records = await self._extract_delinquent_records(page, county, city)

        # Handle pagination
        page_num = 1
        while len(records) < limit and page_num < 10:
            next_btn = await page.query_selector(
                "a:has-text('Next'), button:has-text('Next'), "
                ".pagination .next, a[rel='next']"
            )
            if not next_btn:
                break
            try:
                await next_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay(2.0, 3.0)
                page_records = await self._extract_delinquent_records(page, county, city)
                if not page_records:
                    break
                records.extend(page_records)
                page_num += 1
            except Exception:
                break

        return records[:limit]

    async def _extract_delinquent_records(
        self, page, county: str, city: str
    ) -> list[RawRecord]:
        """Extract delinquent tax records from the current page."""
        records: list[RawRecord] = []

        # Try table rows first
        rows = await page.query_selector_all(
            "table.delinquent tr:not(:first-child), "
            "table#delinquent tr:not(:first-child), "
            ".delinquent-row, table.results tr:not(:first-child), "
            "table tr:not(:first-child)"
        )

        for row in rows[:200]:
            try:
                cells = await row.query_selector_all("td")
                cell_texts = [(await c.inner_text()).strip() for c in cells]
                if not cell_texts or all(not t for t in cell_texts):
                    continue

                record = self._parse_row(cell_texts, county, city)
                if record:
                    records.append(record)
            except Exception as exc:
                logger.debug("[delinquent_tax] Row parse error: %s", exc)

        # If no table rows, try parsing the page text
        if not records:
            try:
                full_text = await page.inner_text("main, .content, body")
                records = self._parse_text_block(full_text, county, city)
            except Exception:
                pass

        return records

    def _parse_row(self, cells: list[str], county: str, city: str) -> RawRecord | None:
        """Parse a table row into a delinquent tax record.

        Common column patterns across KY county PVA sites:
          [Parcel ID | Owner Name | Property Address | Amount Owed | Years Delinquent]
          [Owner Name | Address | Tax Year | Amount | Status]
        """
        if len(cells) < 2:
            return None

        data: dict[str, Any] = {
            "county": county,
            "city": city,
            "source": "delinquent_tax_table",
            "raw_cells": cells,
        }

        # Heuristic column detection
        for cell in cells:
            # Parcel number: typically alphanumeric with dashes
            if re.match(r"^\d{3}-\d{2}-\d{2}-\d+", cell) or re.match(r"^\d{10,}", cell):
                data["parcel_number"] = cell
            # Address: has a street number + word
            elif re.match(r"^\d+\s+[A-Za-z]", cell) and len(cell) > 8:
                data["property_address"] = cell
            # Dollar amount
            elif re.match(r"^\$?\d[\d,\.]+$", cell.replace(",", "").replace("$", "").replace(".", "")):
                if "amount_owed" not in data:
                    data["amount_owed"] = parse_currency(cell)
            # Years delinquent
            elif re.match(r"^\d{1,2}$", cell) and int(cell) < 20:
                data["years_delinquent"] = int(cell)
            # Tax year
            elif re.match(r"^20\d{2}$", cell):
                data["tax_year"] = cell
            # Owner name (fallback: longest text cell that's not an address)
            elif len(cell) > 5 and "owner_name" not in data:
                if not re.match(r"^\d", cell):  # Doesn't start with a number
                    data["owner_name"] = cell

        # Must have at least owner name OR parcel number
        if not data.get("owner_name") and not data.get("parcel_number"):
            return None

        # Must have amount owed to be a real delinquent record
        if not data.get("amount_owed"):
            return None

        data["tax_delinquent"] = True
        return RawRecord(source_key=self.source_key, data=data)

    def _parse_text_block(
        self, text: str, county: str, city: str
    ) -> list[RawRecord]:
        """Parse free-text delinquent list into records."""
        records: list[RawRecord] = []

        # Split on parcel number boundaries or owner name patterns
        # Kentucky parcel format: XXX-XX-XX-XXX or 14-digit numbers
        blocks = re.split(r"(?=\d{3}-\d{2}-\d{2}-\d)", text)

        for block in blocks:
            block = block.strip()
            if len(block) < 20:
                continue

            data: dict[str, Any] = {
                "county": county,
                "city": city,
                "source": "delinquent_tax_text",
                "raw_text": block[:500],
                "tax_delinquent": True,
            }

            # Parcel ID
            parcel_match = re.search(r"\d{3}-\d{2}-\d{2}-\d+", block)
            if parcel_match:
                data["parcel_number"] = parcel_match.group(0)

            # Property address
            addr_match = re.search(
                r"\d{1,6}\s+[A-Za-z\s]+(?:St|Ave|Blvd|Dr|Ln|Rd|Ct|Way|Pl|Pike|Cir)",
                block, re.IGNORECASE,
            )
            if addr_match:
                data["property_address"] = addr_match.group(0).strip()

            # Dollar amount owed
            amounts = _AMOUNT_RE.findall(block)
            if amounts:
                parsed_amounts = []
                for amt in amounts:
                    try:
                        val = float(re.sub(r"[^\d.]", "", amt))
                        if val >= 100:  # Minimum realistic tax amount
                            parsed_amounts.append(val)
                    except ValueError:
                        pass
                if parsed_amounts:
                    data["amount_owed"] = max(parsed_amounts)  # Largest = total owed

            if not data.get("parcel_number") and not data.get("amount_owed"):
                continue

            records.append(RawRecord(source_key=self.source_key, data=data))

        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        county = data.get("county", "")
        city = data.get("city", "")

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county.title()}" if county else "KY-Multi",
            lead_type=LeadType.TAX_LIEN,
            owner_name=data.get("owner_name"),
            property_address=data.get("property_address"),
            city=city or None,
            state="KY",
            parcel_number=data.get("parcel_number"),
            estimated_value=None,  # PVA enrichment stage fills this in
            raw_payload=data,
        )
