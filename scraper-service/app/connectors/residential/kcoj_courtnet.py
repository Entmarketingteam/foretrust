"""Kentucky Court of Justice (KCOJ) KYeCourts / CourtNet connector.

Guest public-records search: https://kcoj.kycourts.net/CourtNet/Search/Index
(requires guest registration + login; typically 2 CAPTCHAs per session).

CourtNet 2.0 uses collapsed search panels. This connector targets **Search by
Party/Business** (county + case category + party category + name) — not the
legacy 90-day bulk county/case-type date-range loop.

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

from playwright.async_api import Browser, Page

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto
from app.captcha import detect_and_solve_captcha
from app.config import settings
from app.pipeline.normalize import parse_date

logger = logging.getLogger(__name__)


# Legacy bulk dropdown labels → LeadType (bulk_legacy only)
CASE_TYPE_MAP = {
    "P - Probate": LeadType.PROBATE,
    "D - Domestic Relations": LeadType.DIVORCE,
    "DR - Domestic Relations": LeadType.DIVORCE,
    "CI - Civil": LeadType.FORECLOSURE,
}

# CourtNet 2.0 case category dropdown values (party search)
CASE_CATEGORY_TO_LEAD_TYPE: dict[str, LeadType] = {
    "PROBATE": LeadType.PROBATE,
    "CIVIL": LeadType.FORECLOSURE,
    "DOMESTIC": LeadType.DIVORCE,
    "DOMESTIC RELATIONS": LeadType.DIVORCE,
    "CRIMINAL": LeadType.ESTATE,
}

LEAD_TYPE_TO_CASE_CATEGORY: dict[str, str] = {
    "probate": "PROBATE",
    "estate": "PROBATE",
    "death": "PROBATE",
    "foreclosure": "CIVIL",
    "pre_foreclosure": "CIVIL",
    "divorce": "DOMESTIC",
}

DEFAULT_PARTY_CATEGORY: dict[str, str] = {
    "PROBATE": "All Parties",
    "CIVIL": "Defendant",
    "DOMESTIC": "Respondent",
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

_PARTY_PANEL_TRIGGERS = [
    "button:has-text('Search by Party')",
    "a:has-text('Search by Party')",
    "button:has-text('Party/Business')",
    "a:has-text('Party/Business')",
    "[data-bs-target*='party' i]",
    "[data-target*='party' i]",
    "#party-search .panel-heading",
    ".accordion-button:has-text('Party')",
    "legend:has-text('Party')",
]

_CASE_PANEL_TRIGGERS = [
    "button:has-text('Search by Case')",
    "a:has-text('Search by Case')",
    "button:has-text('Case Search')",
    "a:has-text('Case Search')",
    "[data-bs-target*='case' i]:not([data-bs-target*='party' i])",
    ".accordion-button:has-text('Case')",
    "legend:has-text('Case')",
]


@register
class KCOJCourtNetConnector(BaseConnector):
    source_key = "kcoj_courtnet"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://kcoj.kycourts.net"
    login_url = "https://kcoj.kycourts.net/kyecourts/Login"
    search_url = "https://kcoj.kycourts.net/CourtNet/Search/Index"
    default_schedule = "0 6 * * *"
    respects_robots = False  # Public court records — KRS 61.872 mandates public access

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        party_searches: list[dict[str, Any]] = list(params.get("party_searches") or [])
        from_notices = bool(params.get("from_notices"))
        bulk_legacy = bool(params.get("bulk_legacy", False))
        limit = int(params.get("limit", 50))
        deep_scrape = bool(params.get("deep_scrape", True))

        if not party_searches and not bulk_legacy:
            if not from_notices:
                logger.warning(
                    "[kcoj] No party_searches configured and bulk_legacy=false — "
                    "skipping blind county/case_type loop (CourtNet 2.0 party search only)"
                )
            return []

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            await self._ensure_session(page)

            for search in party_searches:
                try:
                    batch = await self._party_search(page, search, limit, deep_scrape)
                    records.extend(batch)
                except Exception as exc:
                    logger.warning("[kcoj] Party search failed %r: %s", search, exc)
                await human_delay(3.0, 6.0)

            if bulk_legacy:
                counties = params.get("counties", DEFAULT_COUNTIES)
                case_types = params.get("case_types", list(CASE_TYPE_MAP.keys()))
                for county in counties:
                    for case_type in case_types:
                        try:
                            batch = await self._search_county_case_type(
                                page, county, case_type, limit, deep_scrape
                            )
                            records.extend(batch)
                        except Exception as exc:
                            logger.warning(
                                "[kcoj] Legacy bulk failed %s/%s: %s",
                                county,
                                case_type,
                                exc,
                            )
                        await human_delay(3.0, 6.0)

        return records

    @staticmethod
    def _infer_case_category(search: dict[str, Any]) -> str:
        explicit = search.get("case_category")
        if explicit:
            return str(explicit).strip().upper()

        lead_type = search.get("lead_type", "")
        if isinstance(lead_type, LeadType):
            lead_type = lead_type.value
        key = str(lead_type).strip().lower()
        return LEAD_TYPE_TO_CASE_CATEGORY.get(key, "CIVIL")

    @staticmethod
    def _infer_party_category(search: dict[str, Any], case_category: str) -> str | None:
        if search.get("party_category"):
            return str(search["party_category"]).strip()
        return DEFAULT_PARTY_CATEGORY.get(case_category.upper())

    async def _solve_captchas(self, page: Page, passes: int = 2) -> None:
        """CourtNet guest flow often shows CAPTCHA on login and again on search."""
        for _ in range(passes):
            try:
                if await detect_and_solve_captcha(page):
                    await human_delay(1.5, 2.5)
            except Exception as exc:
                logger.warning("[kcoj] CAPTCHA solve skipped: %s", exc)
                break

    async def _ensure_session(self, page: Page) -> None:
        """Log in as guest (if creds set) and land on CourtNet search."""
        username = settings.kcoj_username
        password = settings.kcoj_password
        if not username or not password:
            raise RuntimeError(
                "Set KCOJ_USERNAME and KCOJ_PASSWORD in Doppler (foretrust-scraper) "
                "for your guest CourtNet account."
            )

        await safe_goto(page, self.search_url)
        await human_delay(1.5, 2.5)
        await self._solve_captchas(page, passes=2)

        if "/Login" in (page.url or "") or await page.query_selector(
            "input#Username, input[name='Username'], input[type='text'][name*='user' i]"
        ):
            await safe_goto(page, self.login_url)
            await human_delay(1.0, 2.0)
            await self._solve_captchas(page, passes=1)

            user_el = await page.query_selector(
                "input#Username, input[name='Username'], "
                "input[placeholder*='Username' i], input[type='text']"
            )
            pass_el = await page.query_selector(
                "input#Password, input[name='Password'], input[type='password']"
            )
            if not user_el or not pass_el:
                raise RuntimeError("KCOJ login form not found at " + self.login_url)

            await user_el.fill(username)
            await pass_el.fill(password)
            await human_delay(0.8, 1.5)
            await self._solve_captchas(page, passes=1)

            login_btn = await page.query_selector(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Login'), input[value='Login']"
            )
            if login_btn:
                await login_btn.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
            await human_delay(2.0, 3.0)
            await self._solve_captchas(page, passes=2)

        await safe_goto(page, self.search_url)
        await human_delay(1.5, 2.5)
        await self._solve_captchas(page, passes=2)

        if "/Login" in (page.url or ""):
            raise RuntimeError(
                "KCOJ login failed — still on Login page. Check guest credentials."
            )

    async def _click_panel_triggers(self, page: Page, selectors: list[str]) -> bool:
        for selector in selectors:
            el = await page.query_selector(selector)
            if not el:
                continue
            try:
                await el.click()
                await human_delay(0.8, 1.5)
                return True
            except Exception:
                continue
        return False

    async def _expand_party_search_panel(self, page: Page) -> None:
        """Open the collapsed 'Search by Party/Business' section."""
        if await self._click_panel_triggers(page, _PARTY_PANEL_TRIGGERS):
            return
        # Panel may already be expanded, or use a single visible party form
        party_form = await page.query_selector(
            "input#LastName, input[name='LastName'], "
            "input[name*='LastName' i], input[placeholder*='Last Name' i], "
            "input#BusinessName, input[name*='Business' i]"
        )
        if not party_form:
            logger.debug("[kcoj] Party panel trigger not found — continuing with visible form")

    async def _expand_case_search_panel(self, page: Page) -> None:
        """Open collapsed case/county search (CourtNet 2.0 SearchCriteria_* fields)."""
        if await self._click_panel_triggers(page, _CASE_PANEL_TRIGGERS):
            return
        # Fallback: expand first collapsed accordion on search page
        for selector in (
            ".accordion-button.collapsed",
            "a.accordion-toggle.collapsed",
            ".panel-heading a[data-toggle='collapse']",
        ):
            el = await page.query_selector(selector)
            if el:
                try:
                    await el.click()
                    await human_delay(0.8, 1.5)
                    return
                except Exception:
                    continue

    async def _select_option_fuzzy(
        self, page: Page, selector: str, value: str, *, by_label: bool = True
    ) -> bool:
        """Select dropdown option; bypass Select2 hidden elements using direct JS setting first."""
        # 1. Try Direct JS setting first (instant, works on hidden Select2 selects)
        try:
            ok = await page.evaluate(
                """({ selectors, target }) => {
                  const t = target.toUpperCase();
                  for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (!el || !el.options) continue;
                    for (const opt of el.options) {
                      const text = (opt.text || '').toUpperCase();
                      const val = (opt.value || '').toUpperCase();
                      if (text.includes(t) || val.includes(t)) {
                        el.value = opt.value;
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                      }
                    }
                  }
                  return false;
                }""",
                {
                    "selectors": [s.strip() for s in selector.split(",") if s.strip()],
                    "target": value,
                },
            )
            if ok:
                logger.debug("[kcoj] JS select success for %s -> %s", selector, value)
                return True
        except Exception as exc:
            logger.debug("[kcoj] JS select failed: %s", exc)

        # 2. Native Playwright fallback if visible
        try:
            if by_label:
                await page.select_option(selector, label=value, timeout=3000)
            else:
                await page.select_option(selector, value=value, timeout=3000)
            return True
        except Exception:
            pass

        return False

    async def _fill_via_js(self, page: Page, selector: str, value: str) -> None:
        """Directly set input value on the DOM and trigger frameworks events to bypass CSS blocks."""
        try:
            await page.evaluate(
                """({ selector, value }) => {
                  const el = document.querySelector(selector);
                  if (!el) return;
                  el.value = value;
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                {"selector": selector, "value": value}
            )
        except Exception as e:
            logger.debug("[kcoj] JS fill failed for %s: %s", selector, e)

    async def _party_search(
        self,
        page: Page,
        search: dict[str, Any],
        limit: int,
        deep_scrape: bool,
    ) -> list[RawRecord]:
        """CourtNet 2.0 guest party/business search (no date-range bulk)."""
        county = str(search.get("county", "")).strip()
        last_name = str(search.get("last_name") or search.get("business_name") or "").strip()
        first_name = str(search.get("first_name", "")).strip()
        if not county:
            raise ValueError("party_searches entry requires county")
        if not last_name:
            raise ValueError("party_searches entry requires last_name or business_name")

        case_category = self._infer_case_category(search)
        party_category = self._infer_party_category(search, case_category)

        await safe_goto(page, self.search_url)
        await human_delay(1.0, 2.0)
        await self._solve_captchas(page, passes=2)

        await self._expand_party_search_panel(page)
        await human_delay(0.5, 1.0)

        # CourtNet 2.0 Specific: County selector within Party search has a unique 'dropdownlist' class
        county_sel = "select#SearchCriteria_County.dropdownlist, select#SearchCriteria_County"
        if not await page.query_selector(county_sel):
            raise RuntimeError(
                "KCOJ party search county dropdown not found — "
                "selectors may need update after CourtNet UI change."
            )
        await self._select_option_fuzzy(page, county_sel, county)

        case_cat_sel = "select#CaseType, select[name='CaseType']"
        if await page.query_selector(case_cat_sel):
            if not await self._select_option_fuzzy(page, case_cat_sel, case_category):
                logger.warning(
                    "[kcoj] Case category %s not matched in dropdown", case_category
                )
        await human_delay(0.5, 1.0)

        # Ensure Last Name radio option is selected to make input fields visible
        try:
            await page.evaluate("const r = document.querySelector('input#lastnameOption, input[value=\"lastnameOption\"]'); if (r) r.click();")
            await human_delay(0.5, 1.0)
        except Exception as e:
            logger.debug("[kcoj] Failed to click radio option: %s", e)

        # Fill values via JS to bypass any CSS overlay or visibility blocks
        await self._fill_via_js(page, "input#SearchCriteria_LastName", last_name)
        
        if search.get("business_name"):
            await self._fill_via_js(page, "input#SearchCriteria_BusinessName", last_name)
            
        if first_name:
            await self._fill_via_js(page, "input#SearchCriteria_FirstName", first_name)
            
        await human_delay(0.5, 1.0)

        search_btn_sel = "input#Search, button#Search, input[type='submit'][value='Search']"
        try:
            # Click via JS as well to bypass overlay blocks
            await page.evaluate("""const b = document.querySelector('input#Search, button#Search, input[value="Search"]'); if (b) b.click();""")
            await page.wait_for_load_state("networkidle", timeout=30000)
            await human_delay(1.0, 2.0)
        except Exception as e:
            logger.warning("[kcoj] Search submit click failed: %s", e)

        await self._solve_captchas(page, passes=2)

        await self._solve_captchas(page, passes=2)

        records = await self._parse_search_results(
            page,
            county=county,
            case_category=case_category,
            limit=limit,
            deep_scrape=deep_scrape,
            search_meta={
                "search_mode": "party",
                "party_last_name": last_name,
                "party_first_name": first_name or None,
                "party_category": party_category,
                "lead_type_hint": search.get("lead_type"),
            },
        )
        logger.info(
            "[kcoj] party search %s/%s %s: %d records",
            county,
            case_category,
            last_name,
            len(records),
        )
        return records

    async def _parse_search_results(
        self,
        page: Page,
        *,
        county: str,
        case_category: str,
        limit: int,
        deep_scrape: bool,
        search_meta: dict[str, Any],
        case_type_label: str | None = None,
    ) -> list[RawRecord]:
        """Parse the results table after any search submit."""
        records: list[RawRecord] = []
        rows = await page.query_selector_all(
            "tr.data-row, table.results tr:not(:first-child), "
            ".search-results tr, #SearchResults tr:not(:first-child)"
        )

        for row in rows[:limit]:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                cell_texts = [(await cell.inner_text()).strip() for cell in cells]

                link_el = await row.query_selector(
                    "a[href*='casesearch'], a[href*='case'], a[href*='CourtNet']"
                )
                case_href = await link_el.get_attribute("href") if link_el else None

                base_data: dict[str, Any] = {
                    **search_meta,
                    "county": county,
                    "case_category": case_category,
                    "case_type": case_type_label or case_category,
                    "cells": cell_texts,
                    "name": cell_texts[0] if cell_texts else "",
                    "case_id": cell_texts[1] if len(cell_texts) > 1 else "",
                    "filed_date": cell_texts[2] if len(cell_texts) > 2 else "",
                    "case_description": cell_texts[3] if len(cell_texts) > 3 else "",
                    "case_status": cell_texts[4] if len(cell_texts) > 4 else "",
                }

                if deep_scrape and case_href:
                    try:
                        detail_url = (
                            case_href
                            if case_href.startswith("http")
                            else f"{self.base_url.rstrip('/')}{case_href}"
                        )
                        detail = await self._extract_case_detail(page, detail_url)
                        base_data.update(detail)
                        await page.go_back()
                        await human_delay(1.5, 3.0)
                    except Exception as exc:
                        logger.debug(
                            "[kcoj] Case detail failed for %s: %s",
                            base_data.get("case_id"),
                            exc,
                        )

                records.append(RawRecord(source_key=self.source_key, data=base_data))

            except Exception as exc:
                logger.debug("[kcoj] Row parse error: %s", exc)

        return records

    async def _search_county_case_type(
        self, page: Page, county: str, case_type: str, limit: int, deep_scrape: bool
    ) -> list[RawRecord]:
        """Legacy 90-day bulk search — only when params bulk_legacy=true."""
        await safe_goto(page, self.search_url)
        await human_delay(1.0, 2.0)
        await self._solve_captchas(page, passes=2)

        await self._expand_case_search_panel(page)
        await human_delay(0.5, 1.0)

        county_sel = (
            "select#SearchCriteria_County, select[name='SearchCriteria.County'], "
            "select#County, select[name='County'], select[name*='county' i]"
        )
        if not await page.query_selector(county_sel):
            raise RuntimeError(
                "KCOJ search form not found at CourtNet/Search/Index — "
                "selectors may need update after guest UI change."
            )
        if not await self._select_option_fuzzy(page, county_sel, county):
            raise RuntimeError(f"KCOJ could not select county {county!r}")
        await human_delay(1.0, 2.0)

        case_sel = (
            "select#SearchCriteria_CaseType, select[name='SearchCriteria.CaseType'], "
            "select#CaseType, select[name='CaseType'], select[name*='case' i]"
        )
        if await page.query_selector(case_sel):
            if not await self._select_option_fuzzy(page, case_sel, case_type):
                logger.debug("[kcoj] Case type %s not in dropdown; skipping filter", case_type)
            await human_delay(1.0, 2.0)

        today = date.today()
        filed_from = today - timedelta(days=90)
        for sel, value in [
            ("input#FiledDateFrom, input[name='FiledDateFrom'], input[name*='From' i]", filed_from),
            ("input#FiledDateTo, input[name='FiledDateTo'], input[name*='To' i]", today),
        ]:
            el = await page.query_selector(sel)
            if el:
                await el.fill(value.strftime("%m/%d/%Y"))

        search_btn = await page.query_selector(
            "input#Search, button#Search, button[type='submit'], "
            "input[type='submit'], button:has-text('Search')"
        )
        if search_btn:
            await search_btn.click()
            await page.wait_for_load_state("networkidle", timeout=30000)
            await human_delay()

        await self._solve_captchas(page, passes=2)

        records = await self._parse_search_results(
            page,
            county=county,
            case_category=case_type,
            limit=limit,
            deep_scrape=deep_scrape,
            search_meta={"search_mode": "bulk_legacy"},
            case_type_label=case_type,
        )
        logger.info("[kcoj] legacy %s/%s: %d records", county, case_type, len(records))
        return records

    async def _extract_case_detail(self, page: Page, url: str) -> dict:
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
            plaintiffs = [
                p
                for p in parties
                if "PLAINTIFF" in p.get("role", "").upper()
                or "PETITIONER" in p.get("role", "").upper()
            ]
            defendants = [
                p
                for p in parties
                if "DEFENDANT" in p.get("role", "").upper()
                or "RESPONDENT" in p.get("role", "").upper()
            ]
            if plaintiffs:
                detail["plaintiff"] = plaintiffs[0]["name"]
                detail["plaintiff_attorney"] = plaintiffs[0].get("attorney", "")
            if defendants:
                detail["defendant"] = defendants[0]["name"]
                detail["defendant_attorney"] = defendants[0].get("attorney", "")

        amounts = _AMOUNT_RE.findall(full_text)
        if amounts:
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

        addr_matches = _ADDR_RE.findall(full_text)
        if addr_matches:
            detail["property_address_in_case"] = addr_matches[0].strip()
            detail["all_addresses_in_case"] = [a.strip() for a in addr_matches[:5]]

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

        mc_match = re.search(
            r"(?:master commissioner|mc sale|commissioner.*sale)[^\n]*?(\d{1,2}/\d{1,2}/\d{4})",
            full_text,
            re.IGNORECASE,
        )
        if mc_match:
            detail["mc_sale_date"] = mc_match.group(1)

        return detail

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        case_type = data.get("case_type", "")
        case_category = (data.get("case_category") or "").upper()

        if case_category in CASE_CATEGORY_TO_LEAD_TYPE:
            lead_type = CASE_CATEGORY_TO_LEAD_TYPE[case_category]
        else:
            lead_type = CASE_TYPE_MAP.get(case_type, LeadType.PROBATE)

        if lead_type == LeadType.FORECLOSURE:
            desc = (data.get("case_description") or "").upper()
            full_text = " ".join(str(v) for v in data.values()).upper()
            if not any(kw in full_text for kw in FORECLOSURE_KEYWORDS):
                lead_type = LeadType.ESTATE

        if lead_type == LeadType.PROBATE:
            desc = (data.get("case_description") or "").upper()
            if any(kw in desc for kw in ["TRUST", "ESTATE OF", "ADMIN"]):
                lead_type = LeadType.ESTATE

        county = data.get("county", "")
        filed_date = parse_date(data.get("filed_date", ""))
        property_address = data.get("property_address_in_case") or None

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
