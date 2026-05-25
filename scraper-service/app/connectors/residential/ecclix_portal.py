"""eCCLIX Central search automation.

Nav (Instruments menu, May 2026):
  - Index Search          → wholesale: Type + Between Dates (instrinq/indexinq)
  - Combination Party Search → name lookups from legal notices
  - Linked Document Search   → related instruments (not wired yet)

Page body may still say "Instrument Search" while the menu says "Index Search".
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from app.browser import human_delay, human_type, safe_goto
from app.captcha import detect_and_solve_captcha

logger = logging.getLogger(__name__)

# Instruments ▼ submenu labels (exact text from portal)
MENU_INDEX_SEARCH = "Index Search"
MENU_COMBINATION_PARTY = "Combination Party Search"
MENU_LINKED_DOCUMENT = "Linked Document Search"
MENU_DELINQUENT_TAX = "Delinquent Tax"

# Direct URL fallbacks (county builds vary)
INDEX_SEARCH_PATHS = (
    "/ecclix/indexinq.aspx",
    "/ecclix/instrinq.aspx",
)
COMBINATION_PARTY_PATHS = (
    "/ecclix/combpartyinq.aspx",
    "/ecclix/cpartyinq.aspx",
    "/ecclix/combpartysrch.aspx",
)
LINKED_DOCUMENT_PATHS = (
    "/ecclix/linkdocinq.aspx",
    "/ecclix/linkeddocinq.aspx",
)
# Delinquent tax has no stable direct URL on all builds — use top menu after subscriber login.
DELINQUENT_TAX_PATHS: tuple[str, ...] = ()

# Nav: Welcome | Instruments ▼ | Securities | Delinquent Tax | Subscriptions | Setup | Logout


async def is_login_page(page) -> bool:
    """True when subscriber login form is shown (not authenticated)."""
    try:
        pwd = page.locator("input[type='password']")
        if await pwd.count() == 0:
            return False
        body = (await page.inner_text("body"))[:2500].lower()
        if "forgot password" in body or "user name" in body:
            return True
        url = (page.url or "").lower()
        return "login.aspx" in url
    except Exception:
        return False


async def select_county_if_needed(page, county: str) -> bool:
    """Click 'Search {County} Records' on usercounties.aspx (eCCLIX Central)."""
    if await is_login_page(page):
        return False
    name = county.strip().title()
    url = (page.url or "").lower()
    if "usercounties.aspx" not in url and await verify_county_context(page, county):
        return True
    if "usercounties.aspx" not in url:
        await safe_goto(page, "https://www.ecclix.com/ecclix/usercounties.aspx")
        await human_delay(1.0, 1.5)
    loc = page.get_by_role(
        "link", name=re.compile(rf"Search\s+{re.escape(name)}\s+Records", re.I)
    )
    if await loc.count() == 0:
        loc = page.locator(f"a:has-text('Search {name} Records')")
    if await loc.count() == 0:
        logger.warning("[ecclix] no 'Search %s Records' link", name)
        return False
    try:
        await loc.first.click()
        await page.wait_for_function(
            "() => !window.location.href.toLowerCase().includes('usercounties.aspx')",
            timeout=45000,
        )
    except Exception:
        logger.warning(
            "[ecclix] county %s — still on picker after click url=%s", name, page.url
        )
        return False
    await human_delay(1.5, 2.5)
    logger.info("[ecclix] selected county %s url=%s", name, page.url)
    return await verify_county_context(page, county)


async def ensure_logged_in(
    page, portal_base: str, username: str, password: str
) -> bool:
    """Re-login if session dropped to login.aspx."""
    if await is_login_page(page):
        logger.warning("[ecclix] session expired — re-login")
        await login(page, portal_base, username, password)
    return not await is_login_page(page)


async def login(page, portal_base: str, username: str, password: str) -> None:
    base = portal_base.rstrip("/")
    for start_url in (
        f"{base}/ecclix/login.aspx",
        f"{base}/login.aspx",
        base,
    ):
        await safe_goto(page, start_url)
        await human_delay(1.0, 1.5)
        if await page.query_selector("input[type='password']"):
            break
        sub = page.get_by_role("link", name=re.compile(r"subscriber\s+login", re.I))
        if await sub.count() > 0:
            await sub.first.click()
            await human_delay(1.5, 2.5)
            break
    await human_delay(1.0, 2.0)
    await detect_and_solve_captcha(page)

    filled_user = False
    for user_sel in (
        "input#UserName", "input#username", "input[name='UserName']",
        "input[name='username']",
    ):
        if await page.query_selector(user_sel):
            await human_type(page, user_sel, username)
            filled_user = True
            break
    if not filled_user:
        loc = page.get_by_label(re.compile(r"user\s*name", re.I))
        if await loc.count() > 0:
            await loc.first.fill(username)
            filled_user = True
    await human_delay(0.4, 0.8)

    filled_pass = False
    for pass_sel in (
        "input#Password", "input#password", "input[name='Password']",
        "input[type='password']",
    ):
        if await page.query_selector(pass_sel):
            await human_type(page, pass_sel, password)
            filled_pass = True
            break
    await human_delay(0.4, 0.8)
    await detect_and_solve_captcha(page)

    for btn in (
        page.get_by_role("button", name=re.compile(r"^Log\s*In$", re.I)),
        page.locator("input[type='submit'][value*='Log' i]"),
        page.locator("input[type='image'][alt*='Log' i]"),
    ):
        if await btn.count() > 0:
            await btn.first.click()
            break
    try:
        await page.wait_for_url(
            re.compile(
                r".*(usercounties|welcome|ecclix/(?!login)|default\.aspx).*",
                re.I,
            ),
            timeout=45000,
        )
    except Exception:
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
    await human_delay(2.0, 3.0)

    if await is_login_page(page):
        logger.error("[ecclix] login failed — still on login form url=%s", page.url)
    else:
        url = (page.url or "").lower()
        if "usercounties.aspx" not in url and "/ecclix/" not in url:
            await safe_goto(page, f"{base}/ecclix/usercounties.aspx")
            await human_delay(1.5, 2.5)
        logger.info("[ecclix] login ok base=%s url=%s", base, page.url)


async def _page_has_index_search_form(page) -> bool:
    """Detect Type + date search form (Index / Instrument Search)."""
    url = (page.url or "").lower()
    if "instrinq" in url or "indexinq" in url:
        return True
    body = ""
    try:
        body = await page.inner_text("body")
    except Exception:
        return False
    if re.search(r"Between\s+Dates", body, re.I):
        return True
    if re.search(r"Instrument\s+Type|Type\s+of\s+Instrument", body, re.I):
        return True
    if await page.get_by_label("Beginning Date").count() > 0:
        return True
    if await page.query_selector("select[name*='Type' i], select[id*='Type' i]"):
        return True
    return False


async def session_established(page) -> bool:
    """Logged in and on an eCCLIX app page (not login.aspx)."""
    if await is_login_page(page):
        return False
    url = (page.url or "").lower()
    if "ecclix" not in url:
        return False
    try:
        body = (await page.inner_text("body"))[:4000].lower()
    except Exception:
        return True
    markers = ("logout", "delinquent tax", "instruments", "securities", "welcome")
    return any(m in body for m in markers)


async def _navigate_instruments_submenu(page, menu_label: str) -> bool:
    """Click Instruments ▼ → submenu item."""
    patterns = [
        page.get_by_role("link", name=re.compile(re.escape(menu_label), re.I)),
        page.get_by_role("menuitem", name=re.compile(re.escape(menu_label), re.I)),
        page.locator(f"a:has-text('{menu_label}')"),
    ]
    for loc in patterns:
        if await loc.count() > 0:
            await loc.first.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            await human_delay(1.5, 2.5)
            logger.info("[ecclix] menu → %s url=%s", menu_label, page.url)
            return True

    # Expand Instruments dropdown first
    inst = page.get_by_role("link", name=re.compile(r"^Instruments\b", re.I))
    if await inst.count() > 0:
        await inst.first.click()
        await human_delay(0.6, 1.0)
    for loc in patterns:
        if await loc.count() > 0:
            await loc.first.click()
            await human_delay(1.5, 2.5)
            logger.info("[ecclix] menu Instruments → %s", menu_label)
            return True
    return False


async def _open_search_page(page, portal_base: str, paths: tuple[str, ...], menu_label: str) -> None:
    base = portal_base.rstrip("/")
    for path in paths:
        await safe_goto(page, f"{base}{path}")
        await human_delay(1.2, 2.0)
        if await _page_has_index_search_form(page) or menu_label != MENU_INDEX_SEARCH:
            return

    if await _navigate_instruments_submenu(page, menu_label):
        return

    # Legacy label on some counties
    if menu_label == MENU_INDEX_SEARCH:
        await _navigate_instruments_submenu(page, "Instrument Search")


async def goto_index_search(page, portal_base: str) -> None:
    """Open Index Search (Type + Between Dates) — primary wholesale form."""
    await _open_search_page(page, portal_base, INDEX_SEARCH_PATHS, MENU_INDEX_SEARCH)
    if not await _page_has_index_search_form(page):
        logger.warning("[ecclix] Index Search form not detected url=%s", page.url)


async def goto_combination_party_search(page, portal_base: str) -> None:
    """Open Combination Party Search for grantor/grantee name queries."""
    await _open_search_page(
        page, portal_base, COMBINATION_PARTY_PATHS, MENU_COMBINATION_PARTY
    )


async def goto_instrument_search(page, portal_base: str) -> None:
    """Alias — menu says Index Search; page title may say Instrument Search."""
    await goto_index_search(page, portal_base)


async def _page_has_delinquent_tax_form(page) -> bool:
    """Delinquent tax search form or results grid (gridSearch)."""
    url = (page.url or "").lower()
    if "usercounties.aspx" in url:
        return False
    if any(p in url for p in ("dtsearch", "delinquent", "dtbill", "dtbilmnt")):
        return True
    try:
        body = (await page.inner_text("body"))[:5000]
    except Exception:
        return False
    if re.search(r"Tax\s+Year|Bill\s*#|gridSearch", body, re.I):
        return True
    if await page.query_selector("table[id*='gridSearch' i], table[id*='Grid' i]"):
        return True
    return False


async def goto_delinquent_tax_search(page, portal_base: str) -> None:
    """Open Delinquent Tax search via top menu (subscriber portal only)."""
    if await is_login_page(page):
        return
    # Delinquent Tax may be a dropdown on some county builds
    dt = page.get_by_role("link", name=re.compile(r"Delinquent\s+Tax", re.I))
    if await dt.count() > 0:
        await dt.first.click()
        await human_delay(0.8, 1.2)
        idx = page.get_by_role("link", name=re.compile(r"Index\s+Search", re.I))
        if await idx.count() > 0:
            await idx.first.click()
            await human_delay(1.5, 2.5)
        else:
            await human_delay(1.0, 1.5)
    else:
        await _navigate_top_menu(page, MENU_DELINQUENT_TAX)
        await human_delay(1.5, 2.5)
    if not await _page_has_delinquent_tax_form(page):
        logger.warning(
            "[ecclix] delinquent tax form not detected after menu url=%s", page.url
        )
    else:
        logger.info("[ecclix] delinquent tax page url=%s", page.url)


async def goto_securities_search(page, portal_base: str) -> None:
    """Securities → Index Search (city liens, judgments)."""
    await _navigate_top_menu(page, "Securities")
    await _navigate_instruments_submenu(page, MENU_INDEX_SEARCH)


async def _navigate_top_menu(page, menu_label: str) -> None:
    patterns = [
        page.get_by_role("link", name=re.compile(re.escape(menu_label), re.I)),
        page.locator(f"a:has-text('{menu_label}')"),
    ]
    for loc in patterns:
        if await loc.count() > 0:
            await loc.first.click()
            await human_delay(1.0, 1.8)
            return


async def fill_county_on_form(page, county: str) -> bool:
    """Some eCCLIX builds have a county dropdown on delinquent tax search."""
    if not county:
        return False
    name = county.strip().title()
    for label in ("County", "Jurisdiction"):
        loc = page.get_by_label(label)
        if await loc.count() > 0:
            try:
                await loc.first.select_option(label=name)
                return True
            except Exception:
                try:
                    await loc.first.select_option(value=name)
                    return True
                except Exception:
                    pass
    sel = await page.query_selector(
        "select[name*='County' i], select[id*='County' i]"
    )
    if sel:
        try:
            await sel.select_option(label=re.compile(name, re.I))
            return True
        except Exception:
            pass
    return False


async def fill_tax_year(page, year: int) -> bool:
    for label in ("Tax Year", "Year"):
        loc = page.get_by_label(label)
        if await loc.count() > 0:
            await loc.first.fill(str(year))
            return True
    el = await page.query_selector(
        "input[name*='TaxYear' i], input[id*='TaxYear' i], input[name*='Year' i]"
    )
    if el:
        await el.fill(str(year))
        return True
    return False


async def drill_instrument_summary_row(page, inst_code: str) -> bool:
    """After type+date search: click LP / count link to open detail grid."""
    code = inst_code.upper()
    for loc in (
        page.get_by_role("link", name=re.compile(rf"^{re.escape(code)}$", re.I)),
        page.locator(f"a:has-text('{code}')"),
    ):
        if await loc.count() > 0:
            await loc.first.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                pass
            await human_delay(2.0, 3.0)
            logger.info("[ecclix] drilled summary → %s detail url=%s", code, page.url)
            return True
    # Hyperlink on instrument count column (e.g. "89")
    rows = await page.query_selector_all("table tr")
    for row in rows:
        text = (await row.inner_text()).strip()
        if not text.upper().startswith(code):
            continue
        link = await row.query_selector("a")
        if link:
            await link.click()
            await human_delay(2.0, 3.0)
            return True
    return False


async def click_next_page(page) -> bool:
    """ASP.NET grid Next > (delinquent tax + instrument detail grids)."""
    for loc in (
        page.get_by_role("link", name=re.compile(r"Next\s*>", re.I)),
        page.locator("a:has-text('Next >')"),
        page.locator("a[href*='Page$Next']"),
    ):
        if await loc.count() == 0:
            continue
        el = loc.first
        cls = (await el.get_attribute("class") or "").lower()
        if "disabled" in cls:
            return False
        try:
            await el.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                pass
            await human_delay(2.0, 3.5)
            return True
        except Exception as exc:
            logger.debug("[ecclix] next page click: %s", exc)
    return False


async def collect_paginated(
    page,
    parse_page_fn,
    *,
    max_pages: int = 80,
    dedupe_key: str = "bill_number",
) -> list[dict[str, Any]]:
    """Walk every results page until Next is gone or no new rows."""
    seen: set[str] = set()
    all_rows: list[dict[str, Any]] = []
    for page_idx in range(max_pages):
        batch = await parse_page_fn(page)
        new_count = 0
        for row in batch:
            key = str(row.get(dedupe_key) or row.get("row_text") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
            new_count += 1
        logger.info(
            "[ecclix] paginate page %d: +%d rows (total %d)",
            page_idx + 1,
            new_count,
            len(all_rows),
        )
        if not await click_next_page(page):
            break
        if new_count == 0:
            break
    return all_rows


async def collect_all_delinquent_tax(
    page,
    portal_base: str,
    tax_year: int,
    *,
    max_pages: int = 80,
    min_amount: float | None = None,
    county: str = "",
) -> list[dict[str, Any]]:
    """Full delinquent tax grid (all pages)."""
    await delinquent_tax_search(page, portal_base, tax_year, county=county)
    if await is_login_page(page):
        return []

    async def _parse(p):
        return await parse_delinquent_tax_rows(
            p, limit=500, min_amount=min_amount
        )

    return await collect_paginated(
        page, _parse, max_pages=max_pages, dedupe_key="bill_number"
    )


async def collect_all_instrument_rows(
    page,
    *,
    max_pages: int = 40,
) -> list[dict[str, Any]]:
    """Instrument detail grid after search/drill (all pages)."""

    async def _parse(p):
        return await parse_result_rows(p, limit=500)

    return await collect_paginated(
        page,
        _parse,
        max_pages=max_pages,
        dedupe_key="row_text",
    )


async def parse_delinquent_tax_rows(
    page, limit: int = 100, min_amount: float | None = 50
) -> list[dict[str, Any]]:
    """Bold/active delinquent tax rows from Delinquent Tax search."""
    if await is_login_page(page):
        return []
    rows_data: list[dict[str, Any]] = []
    row_els = await page.query_selector_all(
        "table[id*='gridSearch' i] tr, table tbody tr, table[id*='Grid'] tr, table.grid tr"
    )
    for row in row_els:
        try:
            text = (await row.inner_text()).strip()
            if not text or "paid" in text.lower() and "bold" not in text.lower():
                if re.search(r"\*\s*paid\s*\*", text, re.I):
                    continue
            cells = await row.query_selector_all("td")
            if len(cells) < 3:
                continue
            cell_texts = [(await c.inner_text()).strip() for c in cells]
            if re.match(r"^(bill|owner|map|amount)", " ".join(cell_texts), re.I):
                if len(text) < 40:
                    continue

            bill_link = await row.query_selector("a")
            href = await bill_link.get_attribute("href") if bill_link else None

            data: dict[str, Any] = {
                "cells": cell_texts,
                "row_text": text,
                "detail_href": href,
                "search_module": "delinquent_tax",
            }
            if len(cell_texts) >= 7:
                data["bill_number"] = cell_texts[0]
                data["tax_year"] = cell_texts[1]
                data["owner_name"] = cell_texts[2]
                data["property_address"] = cell_texts[3]
                data["map_id"] = cell_texts[4]
                data["owed_at_sale"] = cell_texts[5]
                data["amount_due"] = cell_texts[6]
            elif len(cell_texts) >= 5:
                data["bill_number"] = cell_texts[0]
                data["owner_name"] = cell_texts[1]
                data["map_id"] = cell_texts[2]
                data["property_address"] = cell_texts[3]
                data["amount_due"] = cell_texts[4]
            elif len(cell_texts) >= 4:
                data["bill_number"] = cell_texts[0]
                data["owner_name"] = cell_texts[1]
                data["map_id"] = cell_texts[2]
                data["property_address"] = cell_texts[3]
                data["amount_due"] = _extract_dollar(text)

            amt = _extract_dollar(str(data.get("amount_due", "")))
            data["amount_due"] = amt
            if min_amount is not None and amt is not None and amt < min_amount:
                continue
            if min_amount is not None and amt is None:
                continue
            bill = str(data.get("bill_number") or "").strip()
            if not bill.isdigit():
                continue
            if is_junk_portal_row(text, data):
                continue

            rows_data.append(data)
            if len(rows_data) >= limit:
                break
        except Exception as exc:
            logger.debug("[ecclix] delinquent row: %s", exc)
    return rows_data


_LOGIN_JUNK = re.compile(
    r"login\.aspx|forgot\s+password|remember\s+me|user\s*name\s*:|don't have an account|"
    r"payment\s+walkthrough|welcome to ecclix",
    re.I,
)


def is_junk_portal_row(text: str, data: dict[str, Any] | None = None) -> bool:
    """Drop login pages and nav chrome mistaken for grid rows."""
    blob = text or ""
    if data:
        blob = " ".join(
            str(data.get(k) or "")
            for k in (
                "owner_name", "property_address", "row_text", "grantor",
                "grantee", "bill_number", "map_id",
            )
        )
    if len(blob) > 200 and _LOGIN_JUNK.search(blob):
        return True
    if blob.strip().lower().startswith("ecclix") and "log in" in blob.lower():
        return True
    return False


def _extract_dollar(text: str) -> float | None:
    m = re.search(r"\$?\s*([\d,]+\.?\d*)", str(text))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


async def _select_between_dates_tab(page) -> None:
    tab = page.get_by_text("Between Dates", exact=False)
    if await tab.count() > 0:
        await tab.first.click()
        await human_delay(0.5, 1.0)


async def _fill_date_range(page, start: date, end: date) -> bool:
    start_s = start.strftime("%m/%d/%Y")
    end_s = end.strftime("%m/%d/%Y")
    filled = False

    for label, value in (("Beginning Date", start_s), ("Ending Date", end_s)):
        loc = page.get_by_label(label)
        if await loc.count() > 0:
            await loc.first.fill(value)
            filled = True
            continue
        # ASP.NET name fallbacks
        for sel in (
            f"input[id*='{label.replace(' ', '')}' i]",
            f"input[name*='{label.split()[0]}' i]",
        ):
            el = await page.query_selector(sel)
            if el:
                await el.fill(value)
                filled = True
                break

    if not filled:
        inputs = await page.query_selector_all(
            "input[type='text'][placeholder*='MM' i], input[type='text']"
        )
        date_inputs = []
        for inp in inputs:
            ph = (await inp.get_attribute("placeholder") or "").lower()
            name = (await inp.get_attribute("name") or "").lower()
            if "mm" in ph or "date" in name or "date" in ph:
                date_inputs.append(inp)
        if len(date_inputs) >= 2:
            await date_inputs[0].fill(start_s)
            await date_inputs[1].fill(end_s)
            filled = True

    return filled


async def _select_instrument_type(page, inst_code: str) -> bool:
    """Type dropdown in 'By Book' row (DEED, MTG, WILL, LP, ...)."""
    if await is_login_page(page):
        return False

    code = inst_code.upper().strip()
    aliases = {code}
    if code == "LP":
        aliases |= {"LIS PENDENS", "LIS PENDENS ", "LP4"}
    if code == "MTG":
        aliases |= {"MORTGAGE", "MORTGAGES"}
    if code == "DEED":
        aliases |= {"DEEDS"}
    if code == "LIEN":
        aliases |= {"LIENS"}

    selectors = [
        "select[name*='Type' i]",
        "select[id*='Type' i]",
        "select[name*='ddlType' i]",
        "select[id*='ddlType' i]",
    ]

    async def _try_select(el, selector: str) -> bool:
        try:
            options = await el.evaluate(
                """el => Array.from(el.options).map(o => ({
                    value: o.value, text: (o.textContent || '').trim()
                }))"""
            )
        except Exception:
            options = []
        for opt in options:
            text_u = (opt.get("text") or "").upper()
            val_u = (opt.get("value") or "").upper()
            for alias in aliases:
                au = alias.upper()
                if au == text_u or au == val_u or au in text_u or text_u.startswith(au):
                    try:
                        await page.select_option(selector, value=opt["value"])
                        return True
                    except Exception:
                        pass
        for alias in aliases:
            try:
                await page.select_option(selector, label=alias)
                return True
            except Exception:
                try:
                    await page.select_option(selector, value=alias)
                    return True
                except Exception:
                    continue
        return False

    for sel in selectors:
        el = await page.query_selector(sel)
        if el and await _try_select(el, sel):
            return True

    selects = await page.query_selector_all("select")
    for i, sel_el in enumerate(selects[:8]):
        sel = f"select >> nth={i}"
        if await _try_select(sel_el, sel):
            return True

    logger.warning("[ecclix] could not select instrument type %s", inst_code)
    return False


async def submit_instrument_search(page) -> None:
    btn = page.get_by_role("button", name=re.compile(r"^Search$", re.I))
    if await btn.count() > 0:
        await btn.first.click()
    else:
        for sel in (
            "input[type='submit'][value*='Search' i]",
            "input#btnSearch",
            "a:has-text('Search')",
        ):
            el = await page.query_selector(sel)
            if el:
                await el.click()
                break
    try:
        await page.wait_for_load_state("networkidle", timeout=45000)
    except Exception:
        pass
    await human_delay(2.0, 3.5)


async def _fill_party_city_filter(page, city: str) -> bool:
    """Securities search — city / party filter field when present."""
    if not city:
        return False
    for label in ("City", "Party", "Party Name", "Securities Party"):
        loc = page.get_by_label(label)
        if await loc.count() > 0:
            await loc.first.fill(city)
            return True
    for sel in ("input[name*='City' i]", "input[id*='City' i]", "input[name*='Party' i]"):
        el = await page.query_selector(sel)
        if el:
            await el.fill(city)
            return True
    return False


async def instrument_search_by_type(
    page,
    portal_base: str,
    inst_code: str,
    *,
    days_back: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    drill_summary: bool = False,
    use_securities: bool = False,
    party_filter: str = "",
) -> bool:
    """Fill Index Search: Type + Between Dates + Search; optional drill into LP detail."""
    if use_securities:
        await goto_securities_search(page, portal_base)
    else:
        await goto_instrument_search(page, portal_base)

    if await is_login_page(page):
        logger.warning("[ecclix] instrument search aborted — login page")
        return False
    if not await _page_has_index_search_form(page) and not use_securities:
        logger.warning("[ecclix] no index search form url=%s", page.url)
        return False

    await _select_between_dates_tab(page)

    end = end_date or date.today()
    start = start_date or (end - timedelta(days=days_back))

    await _fill_date_range(page, start, end)
    if use_securities and party_filter:
        await _fill_party_city_filter(page, party_filter)
    if not await _select_instrument_type(page, inst_code):
        logger.warning("[ecclix] skip search — type %s not selected", inst_code)
        return False
    await submit_instrument_search(page)
    if await is_login_page(page):
        return False
    if drill_summary:
        await drill_instrument_summary_row(page, inst_code)
    logger.info(
        "[ecclix] search type=%s %s → %s drill=%s url=%s",
        inst_code,
        start.strftime("%m/%d/%Y"),
        end.strftime("%m/%d/%Y"),
        drill_summary,
        page.url,
    )
    return True


async def delinquent_tax_search(
    page,
    portal_base: str,
    tax_year: int,
    *,
    county: str = "",
) -> bool:
    """Delinquent Tax module: tax year only, blank owner/address."""
    if county:
        await select_county_if_needed(page, county)
    await goto_delinquent_tax_search(page, portal_base)
    if await is_login_page(page):
        return False
    if county:
        await fill_county_on_form(page, county)
    await fill_tax_year(page, tax_year)
    await submit_instrument_search(page)
    try:
        await page.wait_for_selector(
            "table[id*='gridSearch' i] tr, table tbody tr td",
            timeout=20000,
        )
    except Exception:
        pass
    await human_delay(1.5, 2.5)
    logger.info("[ecclix] delinquent tax year=%s url=%s", tax_year, page.url)
    return True


async def instrument_search_by_party(
    page,
    portal_base: str,
    party_name: str,
    *,
    days_back: int = 365,
) -> bool:
    """Combination Party Search (preferred) or Index Search party fields."""
    await goto_combination_party_search(page, portal_base)
    end = date.today()
    start = end - timedelta(days=days_back)
    await _select_between_dates_tab(page)
    await _fill_date_range(page, start, end)

    filled = False
    for label in (
        "Party One", "Party 1", "Party Name", "Name", "Grantor", "Grantee",
    ):
        loc = page.get_by_label(label)
        if await loc.count() > 0:
            await loc.first.fill(party_name)
            filled = True
            break
    if not filled:
        party_inp = await page.query_selector(
            "input[name*='Party' i], input[id*='Party' i], input[name*='Name' i]"
        )
        if party_inp:
            await party_inp.fill(party_name)
            filled = True

    if not filled:
        await goto_index_search(page, portal_base)
        await _select_between_dates_tab(page)
        await _fill_date_range(page, start, end)
        for label in ("Party One", "Party 1"):
            loc = page.get_by_label(label)
            if await loc.count() > 0:
                await loc.first.fill(party_name)
                filled = True
                break

    await submit_instrument_search(page)
    logger.info("[ecclix] party search name=%s filled=%s", party_name[:40], filled)
    return filled


async def discovery_search(
    page,
    portal_base: str,
    days_back: int = 30,
    instrument_hint: str | None = None,
) -> bool:
    if not instrument_hint:
        return False
    return await instrument_search_by_type(
        page, portal_base, instrument_hint, days_back=days_back
    )


async def search_by_name(page, name: str, portal_base: str = "https://www.ecclix.com") -> bool:
    return await instrument_search_by_party(page, portal_base, name)


async def search_by_address(page, address: str) -> bool:
    """Legal description search — use Party or Book search; address in legal field if present."""
    logger.debug("[ecclix] address search not on instrinq — use party name or book/page")
    return False


async def verify_county_context(page, county: str) -> bool:
    """Active county session (not the multi-county picker page)."""
    slug = county.lower()
    url = (page.url or "").lower()
    if "usercounties.aspx" in url:
        return False
    if f"{slug}ky.ecclix" in url:
        return True
    try:
        body = (await page.inner_text("body"))[:3000].upper()
        # Welcome line often: "SCOTT COUNTY" or navigation scoped to county
        if f"{slug.upper()} COUNTY" in body:
            return True
        if f"SEARCH {slug.upper()} RECORDS" in body:
            return False
        return f" {slug.upper()} " in f" {body} "
    except Exception:
        return False


async def parse_result_rows(page, limit: int = 50) -> list[dict[str, Any]]:
    if await is_login_page(page):
        return []
    rows_data: list[dict[str, Any]] = []
    row_els = await page.query_selector_all(
        "table tbody tr, table.grid tr, tr.result-row, "
        "table[id*='Grid'] tr, table[id*='grid'] tr"
    )
    for row in row_els[: limit * 3]:
        try:
            text = (await row.inner_text()).strip()
            if not text or len(text) < 12:
                continue
            if re.match(r"^(type|book|page|party|grantor|date|instrument)\b", text, re.I):
                if len(text) < 60:
                    continue

            cells = await row.query_selector_all("td")
            cell_texts = [(await c.inner_text()).strip() for c in cells]

            link = await row.query_selector(
                "a[href*='instr'], a[href*='image'], a[href*='view'], "
                "a[href*='display'], a[href*='doc']"
            )
            href = await link.get_attribute("href") if link else None
            if not href:
                link = await row.query_selector("a")
                href = await link.get_attribute("href") if link else None

            parsed = _parse_row_cells(cell_texts, text)
            if is_junk_portal_row(text, parsed):
                continue
            parsed["detail_href"] = href
            parsed["row_text"] = text
            rows_data.append(parsed)
            if len(rows_data) >= limit:
                break
        except Exception as exc:
            logger.debug("[ecclix] row: %s", exc)

    return rows_data


def _parse_row_cells(cells: list[str], full_text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"cells": cells}
    if len(cells) >= 6:
        data["instrument_type"] = cells[0]
        data["book"] = cells[1]
        data["page"] = cells[2]
        data["grantor"] = cells[3]
        data["grantee"] = cells[4]
        data["recorded_date"] = cells[5]
        data["legal_description"] = cells[6] if len(cells) > 6 else ""
        data["consideration"] = cells[7] if len(cells) > 7 else ""
    elif len(cells) >= 4:
        data["instrument_type"] = cells[0]
        data["book"] = cells[1]
        data["page"] = cells[2]
        data["grantor"] = cells[3]
        data["grantee"] = ""
        data["recorded_date"] = cells[4] if len(cells) > 4 else ""
    else:
        data["instrument_type"] = ""
        m = re.search(r"\b(DEED|MTG|WILL|LP|REL|ENC)\b", full_text, re.I)
        if m:
            data["instrument_type"] = m.group(1).upper()
        bp = re.search(r"\b([A-Z]?\d+[A-Z]?)\s*[-/]\s*(\d+)\b", full_text)
        if bp:
            data["book"], data["page"] = bp.group(1), bp.group(2)
        data["grantor"] = ""
        data["grantee"] = ""
        data["legal_description"] = full_text[:800]
    return data


async def download_document_from_row(
    page,
    row_data: dict[str, Any],
    portal_base: str,
) -> bytes | None:
    href = row_data.get("detail_href")
    if not href:
        return None

    base = portal_base.rstrip("/")
    url = href if href.startswith("http") else f"{base}/{href.lstrip('/')}"
    await safe_goto(page, url)
    await human_delay(2.0, 3.0)
    await detect_and_solve_captcha(page)

    for sel in (
        "a:has-text('Print')", "button:has-text('Print')",
        "input[value*='Print' i]", "#btnPrint",
        "a:has-text('View Image')", "a:has-text('View Document')",
    ):
        el = await page.query_selector(sel)
        if not el:
            continue
        try:
            async with page.expect_download(timeout=60000) as dl_info:
                await el.click()
            download = await dl_info.value
            path = await download.path()
            if path:
                from pathlib import Path
                return Path(path).read_bytes()
        except Exception as exc:
            logger.debug("[ecclix] download %s: %s", sel, exc)

    return None
