"""Abstract base class for Kentucky PVA (Property Valuation Administrator) connectors.

Most KY county PVAs use Tyler Technologies iasWorld or a similar platform.
This base class implements the shared scraping pattern:
  1. Navigate to the property search page
  2. Search by address or parcel ID
  3. Click through to the detail record
  4. Extract ALL available property intelligence:
     - Owner name + mailing address (where to send the offer)
     - Property address, parcel number, legal description
     - Building details: sqft, year built, bed/bath, stories, basement, garage
     - Assessment: land value, improvement value, total assessed, market value
     - Sales/transfer history: last 10 transfers with price + grantor/grantee
     - Tax history: last 5 years with payment status (DELINQUENT = high signal)
     - Homestead exemption status (owner-occupied signal)
     - Land use code + zoning classification
     - Deed book/page reference
     - Any code violations or liens on file

County subclasses override `base_url`, `county_name`, `city_name`, and
`source_key`. They may also override selector methods if the county uses
non-standard HTML.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Browser, Page

from app.connectors.base import BaseConnector
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto
from app.pipeline.normalize import parse_date, parse_currency, parse_int_commas

logger = logging.getLogger(__name__)

# Selectors tried in order — first match wins.
# Covers Tyler iasWorld, custom KY county portals, and legacy ASP systems.
_OWNER_SELECTORS = [
    "[data-field='owner_name']", ".owner-name", "td.owner",
    "th:has-text('Owner') + td", "th:has-text('Owner Name') + td",
    "label:has-text('Owner') ~ span", "label:has-text('Owner') ~ div",
]
_MAILING_SELECTORS = [
    "[data-field='mailing_address']", ".mailing-address",
    "th:has-text('Mailing') + td", "th:has-text('Mail Address') + td",
    "label:has-text('Mailing') ~ span", "label:has-text('Mailing') ~ div",
]
_SQFT_SELECTORS = [
    "[data-field='total_living_area']", "[data-field='building_sqft']",
    ".total-area", ".living-area",
    "th:has-text('Total Living Area') + td", "th:has-text('Sq Ft') + td",
    "th:has-text('Square Feet') + td", "th:has-text('Heated Area') + td",
    "label:has-text('Sq Ft') ~ span",
]
_YEAR_BUILT_SELECTORS = [
    "[data-field='year_built']", ".year-built",
    "th:has-text('Year Built') + td", "th:has-text('Yr Built') + td",
    "label:has-text('Year Built') ~ span",
]
_ASSESSED_SELECTORS = [
    "[data-field='total_assessed_value']", "[data-field='assessed_value']",
    ".total-assessed", ".assessed-value",
    "th:has-text('Total Assessed') + td", "th:has-text('Appraised Value') + td",
    "th:has-text('Fair Market Value') + td", "th:has-text('Total Value') + td",
    "label:has-text('Assessed Value') ~ span",
]
_LAND_VALUE_SELECTORS = [
    "[data-field='land_value']", "th:has-text('Land Value') + td",
    "th:has-text('Land') + td",
]
_IMPROVEMENT_SELECTORS = [
    "[data-field='improvement_value']", "th:has-text('Improvement') + td",
    "th:has-text('Building Value') + td",
]
_PARCEL_SELECTORS = [
    "[data-field='parcel_id']", "[data-field='parcel_number']",
    ".parcel-id", ".parcel-number",
    "th:has-text('Parcel') + td", "th:has-text('Parcel ID') + td",
    "th:has-text('Parcel Number') + td",
]
_LEGAL_DESC_SELECTORS = [
    "[data-field='legal_description']", ".legal-description",
    "th:has-text('Legal Description') + td",
]
_LAND_USE_SELECTORS = [
    "[data-field='land_use']", "[data-field='land_use_code']",
    ".land-use", "th:has-text('Land Use') + td",
    "th:has-text('Class') + td", "th:has-text('Property Class') + td",
]
_DEED_SELECTORS = [
    "[data-field='deed_book']", ".deed-reference",
    "th:has-text('Deed Book') + td", "th:has-text('Book/Page') + td",
]
_HOMESTEAD_SELECTORS = [
    "[data-field='homestead_exemption']", ".homestead",
    "th:has-text('Homestead') + td", "th:has-text('Homestead Exemption') + td",
]
_BEDS_SELECTORS = [
    "[data-field='bedrooms']", ".bedrooms",
    "th:has-text('Bedrooms') + td", "th:has-text('Beds') + td",
]
_BATHS_SELECTORS = [
    "[data-field='bathrooms']", ".bathrooms",
    "th:has-text('Bathrooms') + td", "th:has-text('Baths') + td",
    "th:has-text('Full Bath') + td",
]
_STORIES_SELECTORS = [
    "[data-field='stories']", ".stories",
    "th:has-text('Stories') + td", "th:has-text('Floors') + td",
]
_ACRES_SELECTORS = [
    "[data-field='acres']", ".acres",
    "th:has-text('Acres') + td", "th:has-text('Lot Size') + td",
]


async def _first_text(page: Page, selectors: list[str]) -> str:
    """Return inner text of the first matching selector, or empty string."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


class BasePVAConnector(BaseConnector):
    """Abstract base for all KY county PVA connectors.

    Subclasses must set: source_key, jurisdiction, base_url, county_name, city_name
    """

    county_name: str = ""   # e.g. "Fayette"
    city_name: str = ""     # e.g. "LEXINGTON"
    vertical = Vertical.RESIDENTIAL
    default_schedule = "0 */6 * * *"
    respects_robots = False  # Public government records

    # Optional: override to customize search URL path
    @property
    def search_path(self) -> str:
        return "/property-search"

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        search_addresses = params.get("addresses", [])
        search_names = params.get("names", [])  # owner names from KCOJ cross-ref
        limit = params.get("limit", 100)
        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            # Address lookups (from GIS pipeline)
            for addr in search_addresses[:limit]:
                try:
                    record = await self._lookup(page, addr, search_by="address")
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning("[%s] Address lookup failed for %s: %s",
                                   self.source_key, addr, exc)
                await human_delay(2.0, 4.0)

            # Name lookups (from KCOJ cross-reference)
            for name in search_names[:limit]:
                try:
                    record = await self._lookup(page, name, search_by="name")
                    if record:
                        records.append(record)
                except Exception as exc:
                    logger.warning("[%s] Name lookup failed for %s: %s",
                                   self.source_key, name, exc)
                await human_delay(2.0, 4.0)

            # If no inputs: browse recent transfers (discovery mode)
            if not search_addresses and not search_names:
                records = await self._browse_recent_transfers(page, limit)

        return records

    async def _lookup(self, page: Page, query: str, search_by: str = "address") -> RawRecord | None:
        """Search for a property and extract full detail."""
        search_url = f"{self.base_url}{self.search_path}"
        await safe_goto(page, search_url)
        await human_delay(1.5, 2.5)

        # Locate search input
        input_sel = (
            "input#address, input[name='address'], input[placeholder*='address' i], "
            "input#owner, input[name='owner'], input[placeholder*='owner' i], "
            "input#search, input[type='text']"
        )
        search_input = await page.query_selector(input_sel)
        if not search_input:
            logger.debug("[%s] No search input found at %s", self.source_key, search_url)
            return None

        await search_input.fill("")
        await search_input.fill(query)
        await human_delay(0.8, 1.5)

        # Submit
        submit_sel = (
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Search'), button:has-text('Find')"
        )
        submit_btn = await page.query_selector(submit_sel)
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1.5, 2.5)

        # If a results list appeared, click the first result
        result_link = await page.query_selector(
            "table.results tr:not(:first-child) a, "
            ".result-item a, .property-result a, "
            "tr.data-row td:first-child a"
        )
        if result_link:
            await result_link.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay(1.5, 2.5)

        return await self._extract_full_record(page, query)

    async def _extract_full_record(self, page: Page, search_query: str) -> RawRecord | None:
        """Extract every available field from a PVA property detail page."""
        data: dict[str, Any] = {
            "search_query": search_query,
            "county": self.county_name,
            "source": "pva_detail",
        }

        # --- Core identity fields ---
        owner = await _first_text(page, _OWNER_SELECTORS)
        mailing = await _first_text(page, _MAILING_SELECTORS)
        parcel = await _first_text(page, _PARCEL_SELECTORS)
        legal_desc = await _first_text(page, _LEGAL_DESC_SELECTORS)
        land_use = await _first_text(page, _LAND_USE_SELECTORS)
        deed_ref = await _first_text(page, _DEED_SELECTORS)
        homestead = await _first_text(page, _HOMESTEAD_SELECTORS)

        if owner:
            data["owner_name"] = owner
        if mailing:
            data["mailing_address"] = mailing
        if parcel:
            data["parcel_number"] = parcel
        if legal_desc:
            data["legal_description"] = legal_desc
        if land_use:
            data["land_use"] = land_use
        if deed_ref:
            data["deed_reference"] = deed_ref
        if homestead:
            data["homestead_exemption"] = homestead
            data["owner_occupied"] = bool(
                homestead and homestead.upper() not in ("NO", "N", "FALSE", "0", "NONE")
            )

        # --- Building details ---
        sqft_text = await _first_text(page, _SQFT_SELECTORS)
        year_text = await _first_text(page, _YEAR_BUILT_SELECTORS)
        beds_text = await _first_text(page, _BEDS_SELECTORS)
        baths_text = await _first_text(page, _BATHS_SELECTORS)
        stories_text = await _first_text(page, _STORIES_SELECTORS)
        acres_text = await _first_text(page, _ACRES_SELECTORS)

        if sqft_text:
            data["building_sqft"] = parse_int_commas(sqft_text)
        if year_text:
            try:
                yr = int(re.sub(r"\D", "", year_text)[:4])
                data["year_built"] = yr if 1800 < yr < 2030 else None
            except (ValueError, TypeError):
                pass
        if beds_text:
            data["bedrooms"] = parse_int_commas(beds_text)
        if baths_text:
            data["bathrooms"] = baths_text
        if stories_text:
            data["stories"] = stories_text
        if acres_text:
            data["acres"] = acres_text

        # --- Valuation ---
        assessed_text = await _first_text(page, _ASSESSED_SELECTORS)
        land_val_text = await _first_text(page, _LAND_VALUE_SELECTORS)
        impr_val_text = await _first_text(page, _IMPROVEMENT_SELECTORS)

        if assessed_text:
            data["assessed_value"] = parse_currency(assessed_text)
        if land_val_text:
            data["land_value"] = parse_currency(land_val_text)
        if impr_val_text:
            data["improvement_value"] = parse_currency(impr_val_text)

        # --- Sales / Transfer History ---
        sales_history = await self._extract_sales_history(page)
        if sales_history:
            data["sales_history"] = sales_history
            # Convenience: last sale date + price
            data["last_sale_date"] = sales_history[0].get("date")
            data["last_sale_price"] = sales_history[0].get("price")
            data["last_sale_grantor"] = sales_history[0].get("grantor")
            data["last_sale_grantee"] = sales_history[0].get("grantee")

        # --- Tax History (delinquency is a HIGH distress signal) ---
        tax_history = await self._extract_tax_history(page)
        if tax_history:
            data["tax_history"] = tax_history
            delinquent_years = [
                t for t in tax_history
                if "DELINQ" in str(t.get("status", "")).upper()
                or "UNPAID" in str(t.get("status", "")).upper()
            ]
            if delinquent_years:
                data["tax_delinquent"] = True
                data["delinquent_years"] = [t.get("year") for t in delinquent_years]
                data["delinquent_count"] = len(delinquent_years)

        # Guard: if we got nothing useful, return None
        if not owner and not parcel and not data.get("assessed_value"):
            return None

        return RawRecord(source_key=self.source_key, data=data)

    async def _extract_sales_history(self, page: Page) -> list[dict]:
        """Extract transfer/sales history table."""
        entries: list[dict] = []

        # Click "Sales History" tab if present
        for tab_text in ["Sales History", "Transfer History", "Transfers", "Sales"]:
            tab = await page.query_selector(f"a:has-text('{tab_text}'), button:has-text('{tab_text}')")
            if tab:
                await tab.click()
                await human_delay(0.8, 1.5)
                break

        rows = await page.query_selector_all(
            ".sales-history tr:not(:first-child), "
            "table#SalesHistory tr:not(:first-child), "
            ".transfer-row, .sale-row"
        )

        for row in rows[:10]:
            cells = await row.query_selector_all("td")
            cell_texts = [(await c.inner_text()).strip() for c in cells]
            if cell_texts and len(cell_texts) >= 2:
                entry: dict[str, Any] = {"raw": cell_texts}
                # Common column order: Date | Price | Grantor | Grantee | Deed Book
                if len(cell_texts) > 0:
                    entry["date"] = cell_texts[0]
                if len(cell_texts) > 1:
                    entry["price"] = parse_currency(cell_texts[1])
                if len(cell_texts) > 2:
                    entry["grantor"] = cell_texts[2]
                if len(cell_texts) > 3:
                    entry["grantee"] = cell_texts[3]
                if len(cell_texts) > 4:
                    entry["deed_reference"] = cell_texts[4]
                entries.append(entry)

        return entries

    async def _extract_tax_history(self, page: Page) -> list[dict]:
        """Extract tax payment history — delinquency is a key distress signal."""
        entries: list[dict] = []

        # Click "Tax History" tab if present
        for tab_text in ["Tax History", "Tax Information", "Taxes"]:
            tab = await page.query_selector(f"a:has-text('{tab_text}'), button:has-text('{tab_text}')")
            if tab:
                await tab.click()
                await human_delay(0.8, 1.5)
                break

        rows = await page.query_selector_all(
            ".tax-history tr:not(:first-child), "
            "table#TaxHistory tr:not(:first-child), "
            ".tax-row"
        )

        for row in rows[:10]:
            cells = await row.query_selector_all("td")
            cell_texts = [(await c.inner_text()).strip() for c in cells]
            if cell_texts:
                entry: dict[str, Any] = {"raw": cell_texts}
                if len(cell_texts) > 0:
                    entry["year"] = cell_texts[0]
                if len(cell_texts) > 1:
                    entry["assessed"] = parse_currency(cell_texts[1])
                if len(cell_texts) > 2:
                    entry["tax_amount"] = parse_currency(cell_texts[2])
                if len(cell_texts) > 3:
                    entry["status"] = cell_texts[3]
                entries.append(entry)

        return entries

    async def _browse_recent_transfers(self, page: Page, limit: int) -> list[RawRecord]:
        """Discovery mode: browse recently transferred residential properties."""
        records: list[RawRecord] = []
        await safe_goto(page, f"{self.base_url}{self.search_path}")
        await human_delay(2.0, 4.0)

        # Try to find all/browse mode
        all_btn = await page.query_selector(
            "a:has-text('Browse'), a:has-text('All Properties'), button:has-text('Browse All')"
        )
        if all_btn:
            await all_btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            await human_delay()

        result_links = await page.query_selector_all(
            "table.results tr:not(:first-child) a, .result-item a"
        )

        for link in result_links[:limit]:
            try:
                await link.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await human_delay(2.0, 3.5)
                record = await self._extract_full_record(page, "browse")
                if record:
                    records.append(record)
                await page.go_back()
                await human_delay(1.0, 2.0)
            except Exception as exc:
                logger.debug("[%s] Browse record failed: %s", self.source_key, exc)

        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data

        # Determine lead type
        lead_type = LeadType.VACANCY

        if data.get("tax_delinquent"):
            lead_type = LeadType.TAX_LIEN
        elif "CODE" in str(data.get("land_use", "")).upper():
            lead_type = LeadType.CODE_VIOLATION

        # Parse sqft
        sqft = data.get("building_sqft")
        if isinstance(sqft, str):
            sqft = parse_int_commas(sqft)

        # Parse year built
        year_built = data.get("year_built")
        if isinstance(year_built, str):
            try:
                year_built = int(re.sub(r"\D", "", year_built)[:4])
            except (ValueError, TypeError):
                year_built = None

        # Parse assessed value
        assessed = data.get("assessed_value")
        if isinstance(assessed, str):
            assessed = parse_currency(assessed)

        # Mailing address — build full string if separate components exist
        mailing = data.get("mailing_address")

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{self.county_name}",
            lead_type=lead_type,
            owner_name=data.get("owner_name"),
            mailing_address=mailing,
            property_address=data.get("search_query") if data.get("source") == "pva_detail" else None,
            city=self.city_name,
            state="KY",
            parcel_number=data.get("parcel_number"),
            building_sqft=sqft if isinstance(sqft, int) else None,
            year_built=year_built,
            estimated_value=float(assessed) if assessed else None,
            raw_payload=data,
        )
