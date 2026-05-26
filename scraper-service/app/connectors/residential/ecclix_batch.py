"""eCCLIX wholesaler connector — discovery, download, import clerk instruments.

Modes (params.mode):
  wholesale (default on day pass) — date-range discovery per county, download PDFs,
    full grantor/grantee/legal/consideration → ft_leads + ft_clerk_documents
  address — enrich known lead addresses (legacy)
  name — search grantor/grantee from notice-derived names

Supports YOLO v6 resilient selectors and expanded discovery instruments.
"""

from __future__ import annotations

import logging
import argparse
import asyncio
import sys
import os
from datetime import date, timedelta
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.connectors.residential import ecclix_portal as portal
from app.connectors.residential.ecclix_county_config import (
    COUNTY_PROFILES,
    portal_bases_for,
    wholesale_instrument_codes,
)
from app.connectors.residential.ecclix_row_filters import apply_filters, hot_tier
from app.connectors.residential.ecclix_search_profiles import (
    PARTY_INTEL_SEARCH,
    DAY_PASS_SPRINT,
    CREATIVE_REI_SEARCH,
    DEEP_PORTAL_SEARCH,
    PROFILE_REFERENCE_META,
    SCENARIO_LIBRARY_SEARCH,
    FULL_DAY_PASS_SPRINT,
    SIGNAL_INTEL_SEARCH,
    USABLE_EXTRACT,
    EcclixSearchProfile,
)
from app.pipeline.investment_scorer import best_strategy, score_from_lead_data
from app.pipeline.property_address import normalize_property_address, sanitize_tax_row
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, human_type, safe_goto, create_browser
from app.captcha import detect_and_solve_captcha
from app.config import settings
from app.storage.clerk_documents import (
    extract_address_from_legal,
    insert_clerk_document,
    parse_consideration,
    parse_recorded_date,
    save_document_bytes,
)
from app.storage.supabase_client import insert_leads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CENTRAL_PORTAL = "https://www.ecclix.com"
DISTRESS_INSTRUMENTS = ["WILL", "LP", "DEED", "MTG", "SLIEN", "FLIEN", "AOD", "DJ", "JLIEN", "TLIEN", "LC", "BOND", "WRAP"]

DOC_TYPE_TO_LEAD: list[tuple[str, LeadType]] = [
    ("WILL", LeadType.PROBATE),
    ("PROBATE", LeadType.PROBATE),
    ("DEATH", LeadType.DEATH),
    ("MTG", LeadType.FORECLOSURE),
    ("MORTGAGE", LeadType.FORECLOSURE),
    ("DEED OF TRUST", LeadType.PRE_FORECLOSURE),
    ("LP", LeadType.PRE_FORECLOSURE),
    ("LIS PENDEN", LeadType.PRE_FORECLOSURE),
    ("FORECLOS", LeadType.FORECLOSURE),
    ("FLIEN", LeadType.TAX_LIEN),
    ("SLIEN", LeadType.TAX_LIEN),
    ("LIEN", LeadType.TAX_LIEN),
    ("LC", LeadType.ESTATE),
    ("BOND", LeadType.ESTATE),
    ("WRAP", LeadType.ESTATE),
]

# EXACT SELECTORS from manual source inspection
SEL_TYPE = "select#ctl00_Content_gbSearch_uceType"
SEL_START = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteFdate"
SEL_END = "input#ctl00_Content_gbSearch_calFields_betweenDates_uteLdate"
SEL_SEARCH = "input#ctl00_Content_btnSearch"

@register
class ECCLIXBatchConnector(BaseConnector):
    source_key = "ecclix_batch"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = CENTRAL_PORTAL
    respects_robots = False

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        username = settings.ecclix_username
        password = settings.ecclix_password
        if not username or not password:
            logger.warning("[ecclix] No credentials")
            return []

        mode = params.get("mode", "wholesale")
        if params.get("no_proxy") is None and mode in (
            "delinquent_tax",
            "usable_extract",
            "usable",
            "deep_portal_search",
            "creative_rei_search",
            "scenario_library",
            "pre_mls_sprint",
            "signal_intel",
            "party_intel",
            "party_target",
            "estate_tax_buyer",
        ):
            params = {**params, "no_proxy": True}
        counties = params.get("counties") or settings.ecclix_county_list or [COUNTY_PROFILES[k].name for k in ("scott", "bourbon", "woodford", "franklin") if k in COUNTY_PROFILES]
        download_docs = params.get("download_documents", True)
        days_back = int(params.get("days_back", 30))
        max_per_county = int(params.get("max_documents_per_county", params.get("limit", 25)))
        instrument_types = params.get("instrument_types")

        records: list[RawRecord] = []

        async with create_context(browser) as ctx:
            page = await ctx.new_page()
            try:
                await self._login(page, username, password)

            except Exception as exc:
                logger.error("[ecclix] Fatal session error: %s", exc)

            if mode == "address":
                records = await self._mode_address(page, username, password, counties, params)
            elif mode == "name":
                records = await self._mode_name(page, username, password, counties, params)
            elif mode in ("usable_extract", "usable"):
                params["full_extract"] = True
                params.setdefault("download_documents", False)
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, USABLE_EXTRACT
                )
                await self._export_usable_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
            elif mode in ("signal_intel", "all_lp", "distress_digest"):
                params["full_extract"] = True
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, SIGNAL_INTEL_SEARCH
                )
                await self._export_sprint_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
            elif mode in ("deep_portal_search", "deep_search", "portal_search"):
                params["full_extract"] = True
                params.setdefault("download_documents", True)
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, DEEP_PORTAL_SEARCH
                )
                await self._export_sprint_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
            elif mode in ("creative_rei_search", "creative_finance", "rei_deep"):
                params["full_extract"] = True
                params.setdefault("download_documents", True)
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, CREATIVE_REI_SEARCH
                )
                await self._export_sprint_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
            elif mode in ("party_intel", "party_target", "estate_tax_buyer"):
                params["full_extract"] = True
                params.setdefault("download_documents", True)
                params.setdefault("max_pages", 30)
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, PARTY_INTEL_SEARCH
                )
                await self._export_sprint_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
            elif mode in ("scenario_library", "reference_library", "full_scenario_extract"):
                params["full_extract"] = True
                params.setdefault("download_documents", True)
                params.setdefault("max_pages", 120)
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, SCENARIO_LIBRARY_SEARCH
                )
                names = await self._load_top_owner_names(
                    int(params.get("name_search_limit", 40)),
                    min_tax_due=float(params.get("min_tax_due", 500)),
                )
                if names:
                    records.extend(
                        await self._mode_name(
                            page,
                            username,
                            password,
                            counties,
                            {**params, "names": names, "limit": len(names)},
                        )
                    )
                await self._export_sprint_csv(records, counties)
                await self._export_filtered_manifest(records, counties)
                await self._export_scenario_library(records, counties)
            elif mode in ("full_day_pass", "full_extract"):
                params["full_extract"] = True
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, FULL_DAY_PASS_SPRINT
                )
                await self._export_sprint_csv(records, counties)
            elif mode in ("day_pass_sprint", "sprint"):
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, DAY_PASS_SPRINT
                )
            elif mode in ("pre_mls_sprint", "best_docs", "document_sprint"):
                records = await self._mode_pre_mls_sprint(
                    page, username, password, counties, params
                )
            elif mode in ("lp_recent", "lp"):
                days_back = int(params.get("days_back", 60))
                profiles = (
                    EcclixSearchProfile(
                        key="lp_recent",
                        module="instruments",
                        instrument_type="LP",
                        days_back=days_back,
                        drill_summary=True,
                        max_rows=max_per_county,
                    ),
                )
                records = await self._mode_search_sprint(
                    page, username, password, counties, params, profiles
                )
            elif mode == "delinquent_tax":
                records = await self._mode_delinquent_tax(
                    page, username, password, counties, params
                )
            else:
                records = await self._mode_wholesale(
                    page,
                    username,
                    password,
                    counties,
                    days_back=days_back,
                    instrument_types=instrument_types,
                    max_per_county=max_per_county,
                    download_documents=download_docs,
                )

        logger.info("[ecclix] fetch complete: %d records (mode=%s)", len(records), mode)
        return records

    async def _login(self, page: Page, username: str, password: str) -> None:
        await safe_goto(page, f"{CENTRAL_PORTAL}/ecclix/login.aspx")
        user_f = await page.query_selector("input#txtUsername")
        if user_f:
            await user_f.fill(username)
            await page.fill("input#txtPassword", password)
            await page.click("#btnLogin")
            await page.wait_for_load_state("networkidle")
            if "Force" in await page.content():
                btn = await page.query_selector("input[value*='Force']")
                if btn: await btn.click()
                await page.wait_for_load_state("networkidle")


    async def _resolve_portal_base(
        self, page, county: str, username: str, password: str, *, skip_tax_nav: bool = False
    ) -> str | None:
        """Login and verify we are past login.aspx."""
        bases = list(portal_bases_for(county))
        # Central portal first — delinquent tax grid matches table-scraper exports (Scott)
        bases.sort(key=lambda b: 0 if "www.ecclix.com" in b.lower() else 1)
        for base in bases:
            try:
                await portal.login(page, base, username, password)
                if await portal.is_login_page(page):
                    continue
                if "usercounties.aspx" not in (page.url or "").lower():
                    await safe_goto(page, f"{base.rstrip('/')}/ecclix/usercounties.aspx")
                    await human_delay(1.0, 1.5)
                if not await portal.select_county_if_needed(page, county):
                    logger.error("[ecclix] could not select county %s", county)
                    continue
                if not await portal.session_established(page):
                    continue
                if skip_tax_nav and (
                    await portal._page_has_index_search_form(page)
                    or await portal.verify_county_context(page, county)
                ):
                    logger.info(
                        "[ecclix] county session ok (instruments): %s @ %s",
                        county,
                        page.url,
                    )
                    return base
                # Delinquent tax is the most reliable module on day pass
                await portal.goto_delinquent_tax_search(page, base)
                if await portal.is_login_page(page):
                    continue
                if await portal.session_established(page):
                    logger.info(
                        "[ecclix] county session ok (tax): %s @ %s", county, page.url
                    )
                    return base
                if await portal.verify_county_context(page, county):
                    logger.info("[ecclix] county session ok: %s @ %s", county, page.url)
                    return base
            except Exception as exc:
                logger.debug("[ecclix] base %s failed for %s: %s", base, county, exc)
        logger.error("[ecclix] could not establish session for %s", county)
        return None

    async def _mode_search_sprint(
        self,
        page,
        username: str,
        password: str,
        counties: list[str],
        params: dict[str, Any],
        profiles: tuple[EcclixSearchProfile, ...],
    ) -> list[RawRecord]:
        """Run configured eCCLIX search profiles (day-pass bulk extract)."""
        records: list[RawRecord] = []
        download_documents = params.get("download_documents", False)
        tax_year = int(params.get("tax_year", 2025))
        full_extract = bool(params.get("full_extract"))
        row_delay = 0.4 if full_extract else 2.0
        skip_tax_nav = not any(p.module == "delinquent_tax" for p in profiles)

        for county in counties:
            portal_url = await self._resolve_portal_base(
                page, county, username, password, skip_tax_nav=skip_tax_nav
            )
            if not portal_url:
                continue
            for profile in sorted(profiles, key=lambda p: p.priority):
                try:
                    if not await portal.ensure_logged_in(
                        page, portal_url, username, password
                    ):
                        logger.error("[ecclix] login failed %s — skip profile %s", county, profile.key)
                        continue
                    if profile.module == "delinquent_tax":
                        year = profile.tax_year or tax_year
                        if full_extract:
                            rows = await portal.collect_all_delinquent_tax(
                                page,
                                portal_url,
                                year,
                                max_pages=int(params.get("max_pages", 80)),
                                min_amount=None,
                                county=county,
                            )
                        else:
                            await portal.delinquent_tax_search(
                                page, portal_url, year, county=county
                            )
                            rows = await portal.parse_delinquent_tax_rows(
                                page, limit=profile.max_rows, min_amount=50
                            )
                        logger.info(
                            "[ecclix] %s delinquent_tax %s: %d rows",
                            county, year, len(rows),
                        )
                        kept = 0
                        for row in rows:
                            if profile.filter_tags:
                                ok, reasons = apply_filters(
                                    row,
                                    profile.filter_tags,
                                    min_tax_due=profile.min_tax_due or 0,
                                )
                                if not ok:
                                    continue
                                row["filter_reasons"] = reasons
                                row["hot_tier"] = hot_tier(row, reasons)
                            rec = self._record_from_delinquent(county, row, profile.key)
                            if rec:
                                if row.get("filter_reasons"):
                                    rec.data["filter_reasons"] = row["filter_reasons"]
                                    rec.data["hot_tier"] = row.get("hot_tier")
                                records.append(rec)
                                kept += 1
                        if profile.filter_tags:
                            logger.info(
                                "[ecclix] %s tax filtered: %d/%d kept",
                                county, kept, len(rows),
                            )
                        continue

                    if profile.module == "combination_party":
                        party_q = (profile.party_filter or "").strip()
                        if not party_q:
                            logger.warning(
                                "[ecclix] combination_party missing query %s",
                                profile.key,
                            )
                            continue
                        ok = await portal.instrument_search_by_party(
                            page,
                            portal_url,
                            party_q,
                            days_back=profile.days_back,
                        )
                        if not ok:
                            logger.warning(
                                "[ecclix] party search failed %s/%s",
                                county,
                                profile.key,
                            )
                            continue
                        if full_extract:
                            rows = await portal.collect_all_instrument_rows(
                                page, max_pages=int(params.get("max_pages", 25))
                            )
                        else:
                            rows = await portal.parse_result_rows(
                                page, limit=profile.max_rows
                            )
                        logger.info(
                            "[ecclix] party %s/%s %r: %d rows",
                            county,
                            profile.key,
                            party_q[:30],
                            len(rows),
                        )
                        kept = 0
                        for row in rows:
                            row["search_profile"] = profile.key
                            row["party_query"] = party_q
                            if profile.filter_tags:
                                ok_f, reasons = apply_filters(
                                    row,
                                    profile.filter_tags,
                                    min_tax_due=profile.min_tax_due,
                                )
                                if not ok_f:
                                    continue
                                row["filter_reasons"] = reasons
                                row["hot_tier"] = hot_tier(row, reasons)
                            do_download = download_documents
                            if profile.download_if_pass and profile.filter_tags:
                                do_download = bool(row.get("filter_reasons"))
                            rec = await self._process_instrument_row(
                                page,
                                portal_url,
                                county,
                                row,
                                do_download,
                            )
                            if rec:
                                rec.data["party_query"] = party_q
                                records.append(rec)
                                kept += 1
                            await human_delay(row_delay, row_delay + 0.5)
                        if profile.filter_tags:
                            logger.info(
                                "[ecclix] %s/%s party filtered: %d/%d",
                                county,
                                profile.key,
                                kept,
                                len(rows),
                            )
                        continue

                    end = date.today()
                    if profile.days_back_end:
                        start = end - timedelta(days=profile.days_back)
                        stop = end - timedelta(days=profile.days_back_end)
                    else:
                        start = end - timedelta(days=profile.days_back)
                        stop = end

                    ok = await portal.instrument_search_by_type(
                        page,
                        portal_url,
                        profile.instrument_type,
                        start_date=start,
                        end_date=stop,
                        drill_summary=profile.drill_summary,
                        use_securities=profile.module == "securities",
                        party_filter=profile.party_filter,
                    )
                    if not ok:
                        logger.warning(
                            "[ecclix] search failed %s/%s — skip",
                            county, profile.key,
                        )
                        continue
                    if full_extract and profile.drill_summary:
                        rows = await portal.collect_all_instrument_rows(
                            page, max_pages=int(params.get("max_pages", 40))
                        )
                    else:
                        rows = await portal.parse_result_rows(
                            page, limit=profile.max_rows
                        )
                    logger.info(
                        "[ecclix] sprint %s/%s %s: %d rows",
                        county, profile.key, profile.instrument_type, len(rows),
                    )
                    kept = 0
                    for row in rows:
                        row["search_profile"] = profile.key
                        if profile.filter_tags:
                            ok, reasons = apply_filters(
                                row,
                                profile.filter_tags,
                                min_tax_due=profile.min_tax_due,
                            )
                            if not ok:
                                continue
                            row["filter_reasons"] = reasons
                            row["hot_tier"] = hot_tier(row, reasons)
                        do_download = download_documents
                        if profile.download_if_pass and profile.filter_tags:
                            do_download = bool(row.get("filter_reasons"))
                        rec = await self._process_instrument_row(
                            page,
                            portal_url,
                            county,
                            row,
                            do_download,
                        )
                        if rec:
                            records.append(rec)
                            kept += 1
                        await human_delay(row_delay, row_delay + 0.5)
                    if profile.filter_tags:
                        logger.info(
                            "[ecclix] %s/%s filtered: %d/%d kept",
                            county, profile.key, kept, len(rows),
                        )
                except Exception as exc:
                    logger.error(
                        "[ecclix] sprint %s/%s failed: %s",
                        county, profile.key, exc,
                    )
        return records

    def _record_is_usable(self, d: dict[str, Any]) -> bool:
        from app.connectors.residential.ecclix_portal import is_junk_portal_row

        owner = d.get("owner_name") or d.get("grantor") or ""
        addr = d.get("property_address") or ""
        if is_junk_portal_row(f"{owner} {addr}", d):
            return False
        if d.get("search_module") == "delinquent_tax":
            return bool(owner or addr)
        return bool(owner or addr or d.get("book") or d.get("legal_description"))

    async def _export_usable_csv(
        self, records: list[RawRecord], counties: list[str]
    ) -> None:
        """Clean property list — no login-page junk."""
        import csv
        from datetime import datetime
        from pathlib import Path

        out_dir = Path(__file__).resolve().parents[3] / "exports" / "actionable-leads"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        county_tag = "-".join(counties[:4]) or "multi"
        path = out_dir / f"ecclix-extract-{county_tag}-{stamp}.csv"
        fields = [
            "search_profile", "county", "instrument_type", "owner_name",
            "grantor", "grantee", "property_address", "parcel_number",
            "book", "page", "amount_due", "bill_number",
            "distress_reason", "next_action", "best_strategy",
            "detail_url", "hot_tier",
        ]
        written = 0
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for rec in records:
                d = rec.data
                if not self._record_is_usable(d):
                    continue
                w.writerow({
                    "search_profile": d.get("search_profile"),
                    "county": d.get("county"),
                    "instrument_type": d.get("instrument_type"),
                    "owner_name": d.get("owner_name") or d.get("grantor"),
                    "grantor": d.get("grantor"),
                    "grantee": d.get("grantee"),
                    "property_address": d.get("property_address"),
                    "parcel_number": d.get("parcel_number") or d.get("map_id"),
                    "book": d.get("book"),
                    "page": d.get("page"),
                    "amount_due": d.get("amount_due"),
                    "bill_number": d.get("bill_number"),
                    "distress_reason": d.get("distress_reason"),
                    "next_action": d.get("next_action"),
                    "best_strategy": d.get("best_strategy"),
                    "detail_url": d.get("detail_url"),
                    "hot_tier": d.get("hot_tier"),
                })
                written += 1
        logger.info("[ecclix] usable CSV: %s (%d/%d rows)", path, written, len(records))

    async def _export_sprint_csv(
        self, records: list[RawRecord], counties: list[str]
    ) -> None:
        """Write sprint dump for offline use if Supabase is slow."""
        import csv
        from datetime import datetime
        from pathlib import Path

        out_dir = Path(__file__).resolve().parents[3] / "exports" / "ecclix-sprint"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        county_tag = "-".join(counties[:4]) or "multi"
        path = out_dir / f"{county_tag}-{stamp}.csv"
        fields = [
            "search_profile", "county", "instrument_type", "owner_name",
            "grantor", "grantee", "property_address", "parcel_number",
            "book", "page", "amount_due", "legal_description", "bill_number",
            "distress_reason", "next_action", "best_strategy", "wholesale_score",
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for rec in records:
                d = rec.data
                if not self._record_is_usable(d):
                    continue
                scores = d.get("investment_scores") or {}
                w.writerow({
                    "search_profile": d.get("search_profile"),
                    "county": d.get("county"),
                    "instrument_type": d.get("instrument_type"),
                    "owner_name": d.get("owner_name") or d.get("grantor"),
                    "grantor": d.get("grantor"),
                    "grantee": d.get("grantee"),
                    "property_address": d.get("property_address"),
                    "parcel_number": d.get("parcel_number") or d.get("map_id"),
                    "book": d.get("book"),
                    "page": d.get("page"),
                    "amount_due": d.get("amount_due"),
                    "legal_description": (d.get("legal_description") or "")[:500],
                    "bill_number": d.get("bill_number"),
                    "distress_reason": d.get("distress_reason"),
                    "next_action": d.get("next_action"),
                    "best_strategy": d.get("best_strategy"),
                    "wholesale_score": scores.get("wholesale_score"),
                })
        logger.info("[ecclix] sprint CSV export: %s", path)

    async def _export_filtered_manifest(
        self, records: list[RawRecord], counties: list[str]
    ) -> None:
        """JSON manifest of filter-passing leads for desk review."""
        import json
        from datetime import datetime
        from pathlib import Path

        out_dir = Path(__file__).resolve().parents[3] / "exports" / "portal-intel"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        county_tag = "-".join(counties[:4]) or "multi"
        path = out_dir / f"{county_tag}-filtered-{stamp}.json"

        items = []
        for rec in records:
            d = rec.data
            scores = d.get("investment_scores") or {}
            items.append({
                "hot_tier": d.get("hot_tier", "C"),
                "search_profile": d.get("search_profile"),
                "county": d.get("county"),
                "instrument_type": d.get("instrument_type"),
                "owner_name": d.get("owner_name") or d.get("grantor"),
                "grantee": d.get("grantee"),
                "property_address": d.get("property_address"),
                "legal_description": (d.get("legal_description") or "")[:400],
                "amount_due": d.get("amount_due"),
                "book": d.get("book"),
                "page": d.get("page"),
                "filter_reasons": d.get("filter_reasons", []),
                "best_strategy": d.get("best_strategy"),
                "pre_mls_score": scores.get("pre_mls_score"),
                "short_sale_score": scores.get("short_sale_score"),
                "document_downloaded": d.get("document_downloaded"),
                "storage_path": d.get("storage_path"),
                "creative_scenarios": (scores.get("creative_scenarios") or []),
                "primary_creative_play": scores.get("primary_creative_play"),
                "profile_reference": PROFILE_REFERENCE_META.get(
                    d.get("search_profile") or "", {}
                ),
            })
        items.sort(
            key=lambda x: (
                {"A": 0, "B": 1, "C": 2}.get(x.get("hot_tier", "C"), 3),
                -(x.get("pre_mls_score") or 0),
                -(float(x.get("amount_due") or 0)),
            ),
        )
        path.write_text(
            json.dumps({"count": len(items), "leads": items}, indent=2),
            encoding="utf-8",
        )
        logger.info("[ecclix] filtered manifest: %s (%d leads)", path, len(items))

    async def _export_scenario_library(
        self, records: list[RawRecord], counties: list[str]
    ) -> None:
        """Per-scenario reference folders (good examples for filters/queries)."""
        import json
        import shutil
        from datetime import datetime
        from pathlib import Path

        from app.pipeline.creative_finance_signals import (
            detect_scenarios,
            scenario_outreach_hint,
        )

        root = Path(__file__).resolve().parents[3] / "exports" / "scenario-library"
        stamp = datetime.utcnow().strftime("%Y%m%d")
        county_tag = "-".join(c.lower() for c in counties[:4]) or "multi"
        run_dir = root / f"{county_tag}-{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        by_scenario: dict[str, list[dict]] = {}
        for rec in records:
            d = rec.data
            scores = d.get("investment_scores") or {}
            scenarios = scores.get("creative_scenarios") or detect_scenarios(d)
            if not scenarios:
                scenarios = ["unclassified_distress"]
            item = {
                **d,
                "creative_scenarios": scenarios,
                "primary_creative_play": scores.get("primary_creative_play"),
            }
            for sc in scenarios:
                by_scenario.setdefault(sc, []).append(item)

        index_lines = [
            f"# Scenario library — {county_tag} ({stamp})",
            "",
            "| Scenario | Examples | PDFs |",
            "|----------|----------|------|",
        ]

        for scenario, items in sorted(by_scenario.items(), key=lambda x: -len(x[1])):
            scen_dir = run_dir / scenario
            scen_dir.mkdir(parents=True, exist_ok=True)
            pdf_dir = scen_dir / "pdfs"
            pdf_dir.mkdir(exist_ok=True)

            # Rank: downloaded PDF first, then pre_mls/subto scores
            def _rank(it: dict) -> tuple:
                sc = it.get("investment_scores") or {}
                return (
                    0 if it.get("document_downloaded") else 1,
                    -(sc.get("subto") or 0),
                    -(float(it.get("amount_due") or 0)),
                )

            items_sorted = sorted(items, key=_rank)[:200]
            pdf_count = 0
            for it in items_sorted:
                sp = it.get("storage_path") or ""
                if sp and Path(sp).is_file() and it.get("document_downloaded"):
                    dest = pdf_dir / Path(sp).name
                    if not dest.exists():
                        try:
                            shutil.copy2(sp, dest)
                            pdf_count += 1
                        except OSError:
                            pass

            meta = PROFILE_REFERENCE_META.get(items_sorted[0].get("search_profile", ""), {})
            readme = scen_dir / "README.md"
            readme.write_text(
                "\n".join(
                    [
                        f"# {scenario}",
                        "",
                        f"**Examples in this folder:** {len(items_sorted)}",
                        f"**PDFs copied:** {pdf_count}",
                        "",
                        f"**Outreach hint:** {scenario_outreach_hint(scenario)}",
                        "",
                        "**Intended eCCLIX query (reference):**",
                        f"- {meta.get('query', 'See search_profile on each row')}",
                        "",
                        "**Filter tags (good example):**",
                        f"- `{meta.get('filters', items_sorted[0].get('filter_reasons', []))}`",
                        "",
                        "**Target scenarios:**",
                        f"- `{meta.get('target_scenarios', (scenario,))}`",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            manifest_path = scen_dir / "examples.json"
            manifest_path.write_text(
                json.dumps({"scenario": scenario, "count": len(items_sorted), "leads": items_sorted}, indent=2, default=str),
                encoding="utf-8",
            )

            import csv

            csv_path = scen_dir / "examples.csv"
            if items_sorted:
                keys = [
                    "search_profile", "county", "instrument_type", "owner_name", "grantor",
                    "grantee", "property_address", "amount_due", "book", "page",
                    "filter_reasons", "primary_creative_play", "storage_path",
                    "document_downloaded", "distress_reason",
                ]
                with csv_path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                    w.writeheader()
                    for it in items_sorted:
                        row = {k: it.get(k) for k in keys}
                        row["filter_reasons"] = ",".join(it.get("filter_reasons") or [])
                        w.writerow(row)

            index_lines.append(f"| {scenario} | {len(items_sorted)} | {pdf_count} |")

        (run_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        logger.info("[ecclix] scenario library: %s (%d scenarios)", run_dir, len(by_scenario))

    async def _mode_delinquent_tax(
        self,
        page,
        username: str,
        password: str,
        counties: list[str],
        params: dict[str, Any],
    ) -> list[RawRecord]:
        profile = EcclixSearchProfile(
            key="delinquent_tax",
            module="delinquent_tax",
            tax_year=int(params.get("tax_year", 2025)),
            max_rows=int(params.get("limit", 100)),
        )
        return await self._mode_search_sprint(
            page, username, password, counties, params, (profile,)
        )

    def _record_from_delinquent(
        self, county: str, row: dict[str, Any], profile_key: str
    ) -> RawRecord | None:
        from app.connectors.residential.ecclix_portal import is_junk_portal_row

        if is_junk_portal_row(row.get("row_text", ""), row):
            return None
        row = sanitize_tax_row(row)
        owner = (row.get("owner_name") or "").strip()
        addr = (row.get("property_address") or "").strip()
        if not owner and not addr:
            return None
        amount = row.get("amount_due")
        data = {
            "county": county,
            "owner_name": owner,
            "property_address": addr,
            "parcel_number": row.get("map_id"),
            "amount_due": amount,
            "bill_number": row.get("bill_number"),
            "search_profile": profile_key,
            "search_module": "delinquent_tax",
            "cells": row.get("cells", []),
            "row_text": row.get("row_text"),
        }
        if not data.get("detail_url") and data.get("bill_number"):
            data["detail_url"] = (
                f"https://www.ecclix.com/ecclix/dtbilmntTabbed.aspx?"
                f"BillNumber={data['bill_number']}&TaxYear={data.get('tax_year', 2025)}"
            )
        from app.pipeline.distress_reason import distress_reason, next_action

        data["distress_reason"] = distress_reason({
            "lead_type": "tax_lien",
            "owner_name": owner,
            "property_address": addr,
            "estimated_value": amount,
            "raw_payload": data,
        })
        data["next_action"] = next_action({
            "lead_type": "tax_lien",
            "property_address": addr,
            "raw_payload": data,
        })
        data["investment_scores"] = score_from_lead_data(data)
        data["best_strategy"] = best_strategy(data["investment_scores"])
        return RawRecord(source_key=self.source_key, data=data)

    async def _mode_wholesale(
        self,
        page,
        username: str,
        password: str,
        counties: list[str],
        *,
        days_back: int,
        instrument_types: list[str] | None,
        max_per_county: int,
        download_documents: bool,
    ) -> list[RawRecord]:
        """Wholesaler: Index Search (Type + Between Dates) → download → import."""
        records: list[RawRecord] = []

        for county in counties:
            portal_url = await self._resolve_portal_base(page, county, username, password)
            if not portal_url:
                logger.warning("[ecclix] No portal for %s", county)
                continue

            types = instrument_types or wholesale_instrument_codes(county)
            county_count = 0

            try:
                for inst_type in types:
                    if county_count >= max_per_county:
                        break
                    await portal.instrument_search_by_type(
                        page,
                        portal_url,
                        inst_type,
                        days_back=days_back,
                    )
                    rows = await portal.parse_result_rows(
                        page, limit=max_per_county - county_count
                    )
                    logger.info(
                        "[ecclix] %s / %s: %d result rows",
                        county, inst_type, len(rows),
                    )

                    for row in rows:
                        if county_count >= max_per_county:
                            break
                        rec = await self._process_instrument_row(
                            page,
                            portal_url,
                            county,
                            row,
                            download_documents=download_documents,
                        )
                        if rec:
                            records.append(rec)
                            county_count += 1
                        await human_delay(2.0, 4.0)

            except Exception as exc:
                logger.error("[ecclix] wholesale county %s failed: %s", county, exc)

        return records

    async def _process_instrument_row(
        self,
        page,
        portal_url: str,
        county: str,
        row: dict[str, Any],
        download_documents: bool,
    ) -> RawRecord | None:
        from app.connectors.residential.ecclix_portal import is_junk_portal_row

        inst = (row.get("instrument_type") or "").strip()
        book = str(row.get("book") or "").strip()
        page_no = str(row.get("page") or "").strip()
        if not book and not page_no and not inst:
            return None

        legal = row.get("legal_description") or row.get("row_text") or ""
        grantor = row.get("grantor") or ""
        grantee = row.get("grantee") or ""
        if is_junk_portal_row(legal, row) or is_junk_portal_row(
            f"{grantor} {grantee} {inst}", row
        ):
            return None
        consideration_raw = row.get("consideration") or ""
        recorded = parse_recorded_date(row.get("recorded_date") or "")
        prop_addr = normalize_property_address(
            row.get("property_address"),
            legal=legal,
        ) or extract_address_from_legal(legal)
        consideration = parse_consideration(consideration_raw)

        storage_path = ""
        file_name = ""
        file_hash = ""
        file_bytes: bytes | None = None

        if download_documents:
            file_bytes = await portal.download_document_from_row(page, row, portal_url)
            if file_bytes:
                storage_path, file_name, file_hash = save_document_bytes(
                    county, book, page_no, inst, file_bytes
                )

        doc_row = {
            "source_key": self.source_key,
            "county": county.title(),
            "instrument_type": inst,
            "book": book,
            "page": page_no,
            "recorded_date": recorded.isoformat() if recorded else None,
            "grantor": grantor,
            "grantee": grantee,
            "legal_description": legal[:4000] if legal else None,
            "consideration": consideration,
            "property_address": prop_addr,
            "file_name": file_name or None,
            "storage_path": storage_path or f"pending/{county}/{book}-{page_no}",
            "file_sha256": file_hash or None,
            "raw_payload": {**row, "ecclix_enriched": True},
        }
        await insert_clerk_document(doc_row)

        payload = {
            "county": county,
            "instrument_type": inst,
            "book": book,
            "page": page_no,
            "grantor": grantor,
            "grantee": grantee,
            "owner_name": grantor or grantee,
            "legal_description": legal,
            "consideration": consideration_raw,
            "consideration_amount": consideration,
            "property_address": prop_addr,
            "recorded_date": row.get("recorded_date"),
            "storage_path": storage_path,
            "file_name": file_name,
            "file_sha256": file_hash,
            "document_downloaded": bool(file_bytes),
            "ecclix_enriched": True,
            "search_mode": row.get("search_profile", "wholesale"),
            "search_profile": row.get("search_profile"),
            "lp_active": inst == "LP" or row.get("search_profile", "").startswith("lp"),
            "cells": row.get("cells", []),
            "row_text": row.get("row_text"),
        }
        from app.pipeline.distress_reason import distress_reason, next_action

        lead_type = LeadType.ESTATE
        for needle, lt in DOC_TYPE_TO_LEAD:
            if needle in inst.upper():
                lead_type = lt
                break
        if payload.get("signal_channel") == "city_lien":
            lead_type = LeadType.CODE_VIOLATION
        owner = grantor or grantee
        if lead_type in (LeadType.FORECLOSURE, LeadType.PRE_FORECLOSURE):
            owner = grantee or grantor

        payload["distress_reason"] = distress_reason({
            "lead_type": lead_type.value,
            "owner_name": owner,
            "property_address": payload.get("property_address"),
            "grantor": grantor,
            "grantee": grantee,
            "raw_payload": payload,
        })
        payload["next_action"] = next_action({
            "lead_type": lead_type.value,
            "property_address": payload.get("property_address"),
            "raw_payload": payload,
        })
        payload["investment_scores"] = score_from_lead_data(payload)
        payload["best_strategy"] = best_strategy(payload["investment_scores"])
        return RawRecord(source_key=self.source_key, data=payload)

    async def _mode_pre_mls_sprint(
        self,
        page,
        username: str,
        password: str,
        counties: list[str],
        params: dict[str, Any],
    ) -> list[RawRecord]:
        """LP + instrument PDFs + party search on top tax-delinquent owners."""
        params = {**params, "download_documents": True}
        days_back = int(params.get("days_back", 90))
        max_lp = int(params.get("max_documents_per_county", 35))
        profiles = (
            EcclixSearchProfile(
                key="lp_recent",
                module="instruments",
                instrument_type="LP",
                days_back=days_back,
                drill_summary=True,
                max_rows=max_lp,
            ),
        )
        records = await self._mode_search_sprint(
            page, username, password, counties, params, profiles
        )
        names = params.get("names") or await self._load_top_owner_names(
            int(params.get("name_search_limit", 20)),
            min_tax_due=float(params.get("min_tax_due", 1500)),
        )
        if names:
            name_params = {**params, "names": names, "limit": len(names)}
            records.extend(
                await self._mode_name(page, username, password, counties, name_params)
            )
        await self._export_sprint_csv(records, counties)
        return records

    async def _load_top_owner_names(
        self, limit: int, *, min_tax_due: float = 1500
    ) -> list[str]:
        """Human owners with high tax delinquency — good pre-MLS party search seeds."""
        from app.pipeline.investment_scorer import is_human_owner
        from app.storage.supabase_client import _get_client

        client = _get_client()
        if not client:
            return []
        names: list[str] = []
        try:
            import json

            resp = (
                client.table("ft_leads")
                .select("owner_name,raw_payload,hot_score,source_key")
                .in_("source_key", ["ecclix_batch", "ecclix_csv_import"])
                .not_.is_("owner_name", "null")
                .order("hot_score", desc=True)
                .limit(limit * 8)
                .execute()
            )
            for row in resp.data or []:
                own = (row.get("owner_name") or "").strip()
                if not own or not is_human_owner(own):
                    continue
                payload = row.get("raw_payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                amt = float(
                    payload.get("amount_due")
                    or payload.get("tax_due")
                    or payload.get("total_due")
                    or 0
                )
                if amt < min_tax_due:
                    continue
                if own.lower() not in {n.lower() for n in names}:
                    names.append(own)
                if len(names) >= limit:
                    break
        except Exception as exc:
            logger.warning("[ecclix] top owner names: %s", exc)
        return names

    async def _mode_name(
        self,
        page,
        username: str,
        password: str,
        counties: list[str],
        params: dict[str, Any],
    ) -> list[RawRecord]:
        names = params.get("names", [])
        if not names:
            return []
        records: list[RawRecord] = []
        download_documents = params.get("download_documents", True)
        for county in counties:
            portal_url = await self._resolve_portal_base(page, county, username, password)
            if not portal_url:
                continue
            try:
                for name in names[: params.get("limit", 30)]:
                    await portal.search_by_name(page, name, portal_url)
                    rows = await portal.parse_result_rows(page, limit=10)
                    for row in rows:
                        rec = await self._process_instrument_row(
                            page, portal_url, county, row, download_documents
                        )
                        if rec:
                            rec.data["search_name"] = name
                            records.append(rec)
                    await human_delay(2.0, 4.0)
            except Exception as exc:
                logger.error("[ecclix] name mode %s: %s", county, exc)
        return records

    async def _load_pending_addresses(self, limit: int) -> list[str]:
        from app.pipeline.property_address import is_valid_street_address
        from app.storage.supabase_client import _get_client, get_pending_ecclix_leads

        addrs: list[str] = []
        try:
            for row in await get_pending_ecclix_leads(limit):
                addr = (row.get("property_address") or "").strip()
                if addr and is_valid_street_address(addr) and addr not in addrs:
                    addrs.append(addr)
        except Exception as exc:
            logger.warning("[ecclix] pending leads: %s", exc)

        if len(addrs) >= limit:
            return addrs[:limit]

        client = _get_client()
        if not client:
            return addrs
        try:
            resp = (
                client.table("ft_leads")
                .select("property_address")
                .not_.is_("property_address", "null")
                .order("hot_score", desc=True)
                .limit(limit * 3)
                .execute()
            )
            for row in resp.data or []:
                addr = (row.get("property_address") or "").strip()
                if addr and is_valid_street_address(addr) and addr not in addrs:
                    addrs.append(addr)
                if len(addrs) >= limit:
                    break
        except Exception as exc:
            logger.warning("[ecclix] address fallback: %s", exc)
        return addrs[:limit]

    def parse(self, raw: RawRecord) -> Lead:
        d = raw.data
        dt = (d.get("doc_type") or "").upper()
        lt = LeadType.ESTATE
        for needle, lead_type in DOC_TYPE_TO_LEAD:
            if needle in dt:
                lt = lead_type
                break
        
        if any(x in dt for x in ["MORTGAGE", "FORECLOS", "LP", "DJ", "PENDENS"]): lt = LeadType.FORECLOSURE
        elif any(x in dt for x in ["LIEN", "TAX"]): lt = LeadType.TAX_LIEN

        return Lead(
            source_key=self.source_key, vertical=Vertical.RESIDENTIAL, jurisdiction=f"KY-{d['county'].title()}",
            lead_type=lt, owner_name=d.get("grantor") or d.get("grantee"), property_address=d.get("address"),
            state="KY", case_id=d.get("book_page"), raw_payload=d,
        )

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", type=str)
    parser.add_argument("--start-date", type=str, default="01/01/2026")
    args = parser.parse_args()
    clist = args.counties.split(",") if args.counties else ["Bourbon", "Scott", "Woodford", "Franklin"]
    
    async with create_browser(headless=True) as browser:
        conn = ECCLIXBatchConnector()
        recs = await conn.fetch(browser, {"counties": clist, "start_date": args.start_date, "scrape_taxes": True})
        leads = [conn.parse(r) for r in recs]
        if leads:
            from app.storage.supabase_client import insert_leads
            inserted = await insert_leads(leads)
            logger.info("Persisted %d leads", inserted)

if __name__ == "__main__":
    asyncio.run(main())
