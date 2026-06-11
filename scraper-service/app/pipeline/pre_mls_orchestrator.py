"""Pre-MLS pipeline — distress signals first, property intelligence second.

Optimized for earliest probate / foreclosure / tax signals before MLS listing.
Runs legal notices and court-adjacent sources before bulk GIS discovery.

Stage order:
  1. legal_notices
  2. ky_master_commissioner
  3. ky_delinquent_tax
  4. notice_parse.extract_party_searches → kcoj_courtnet (party_searches, limit 30)
  5. ky_state_gis (default limit 50)
  6. PVA enrichment — notice addresses + KCOJ names + GIS addresses
  7. cross_reference court-like leads ↔ PVA + GIS
  8. score + persist (upsert_leads)

For vacancy-first / full county sweep, use run_full_pipeline in orchestrator.py.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Browser

from app.models import Lead
from app.pipeline.distress_scorer import score_leads
from app.pipeline.enrich import cross_reference_leads
from app.pipeline.notice_parse import extract_party_searches
from app.config import settings
from app.pipeline.orchestrator import COUNTY_PVA_MAP, DEFAULT_COUNTIES

logger = logging.getLogger(__name__)

DEFAULT_GIS_LIMIT = 50
DEFAULT_PARTY_SEARCH_LIMIT = 30


def _court_like_leads(*groups: list[Lead]) -> list[Lead]:
    """Leads from court, tax, MC, or notice sources — candidates for cross-reference."""
    return [lead for group in groups for lead in group]


async def _run_stage(
    browser: Browser,
    source_key: str,
    params: dict[str, Any],
    summary: dict[str, Any],
    stage_key: str | None = None,
) -> list[Lead]:
    """Run a single connector; record status in summary."""
    from app.connectors.registry import get_connector

    key = stage_key or source_key
    logger.info("[pre-mls] Stage: %s", key)
    try:
        conn = get_connector(source_key)
        leads, run = await conn.run(browser, params=params)
        summary["stages"][key] = {"count": len(leads), "status": run.status.value}
        return leads
    except Exception as exc:
        logger.warning("[pre-mls] %s failed: %s", key, exc)
        summary["stages"][key] = {"count": 0, "status": "error", "error": str(exc)}
        return []


async def _run_pva_enrichment(
    browser: Browser,
    counties: list[str],
    notice_leads: list[Lead],
    kcoj_leads: list[Lead],
    gis_leads: list[Lead],
    limit_per_source: int,
    summary: dict[str, Any],
) -> list[Lead]:
    """Route notice addresses, KCOJ names, and GIS addresses to county PVAs."""
    from app.connectors.registry import get_connector

    addresses_by_county: dict[str, list[str]] = {}
    names_by_county: dict[str, list[str]] = {}

    for lead in notice_leads:
        county_raw = (lead.jurisdiction or "").replace("KY-", "").lower()
        if not county_raw and lead.raw_payload.get("detected_county"):
            county_raw = str(lead.raw_payload["detected_county"]).lower()
        addr = lead.property_address
        if county_raw and addr:
            addresses_by_county.setdefault(county_raw, []).append(addr)

    for lead in kcoj_leads:
        county_raw = (lead.jurisdiction or "").replace("KY-", "").lower()
        if county_raw and lead.owner_name:
            names_by_county.setdefault(county_raw, []).append(lead.owner_name)

    for lead in gis_leads:
        county_raw = (lead.jurisdiction or "").replace("KY-", "").lower()
        addr = lead.property_address
        if county_raw and addr:
            addresses_by_county.setdefault(county_raw, []).append(addr)

    pva_leads: list[Lead] = []

    for county_key, pva_source_key in COUNTY_PVA_MAP.items():
        if county_key not in counties and county_key.title() not in counties:
            continue

        addresses = addresses_by_county.get(county_key, [])
        names = names_by_county.get(county_key, [])

        if not addresses and not names:
            continue

        try:
            pva_conn = get_connector(pva_source_key)
            leads, run = await pva_conn.run(
                browser,
                params={
                    "addresses": addresses[:limit_per_source],
                    "names": names[:50],
                    "limit": limit_per_source,
                },
            )
            pva_leads.extend(leads)
            summary["stages"][pva_source_key] = {
                "count": len(leads),
                "status": run.status.value,
                "addresses_queried": len(addresses),
                "names_queried": len(names),
            }
            logger.info(
                "[pre-mls] %s: %d leads (%d addresses, %d names)",
                pva_source_key, len(leads), len(addresses), len(names),
            )
        except Exception as exc:
            logger.warning("[pre-mls] PVA %s failed: %s", pva_source_key, exc)
            summary["stages"][pva_source_key] = {
                "count": 0, "status": "error", "error": str(exc),
            }

    return pva_leads


async def run_pre_mls_pipeline(
    browser: Browser,
    params: dict[str, Any] | None = None,
) -> tuple[list[Lead], dict[str, Any]]:
    """Execute the distress-first pre-MLS pipeline. Persists scored leads to Supabase."""
    params = params or {}
    counties = params.get("counties", DEFAULT_COUNTIES)
    limit_per_source = params.get("limit_per_source", 100)
    gis_limit = params.get("gis_limit", DEFAULT_GIS_LIMIT)
    party_search_limit = params.get("party_search_limit", DEFAULT_PARTY_SEARCH_LIMIT)

    summary: dict[str, Any] = {
        "pipeline": "pre_mls",
        "counties": counties,
        "stages": {},
    }

    # a) Legal notices — earliest signal
    notice_leads = await _run_stage(browser, "legal_notices", {}, summary)

    # b) Master Commissioner — scheduled foreclosure sales
    mc_leads = await _run_stage(
        browser,
        "ky_master_commissioner",
        {"counties": [c.title() for c in counties], "limit": limit_per_source},
        summary,
    )

    # c) Delinquent tax
    tax_leads = await _run_stage(
        browser,
        "ky_delinquent_tax",
        {"counties": counties, "limit": limit_per_source * 2},
        summary,
    )

    # d) Notice-derived party searches → KCOJ
    party_searches = extract_party_searches(notice_leads)[:party_search_limit]
    summary["stages"]["notice_party_searches"] = {"count": len(party_searches)}

    kcoj_leads: list[Lead] = []
    if party_searches:
        kcoj_leads = await _run_stage(
            browser,
            "kcoj_courtnet",
            {
                "party_searches": party_searches,
                "from_notices": True,
                "limit": party_search_limit,
                "deep_scrape": params.get("deep_scrape", True),
            },
            summary,
            stage_key="kcoj_courtnet",
        )
    else:
        logger.info("[pre-mls] No party searches from notices — skipping KCOJ")
        summary["stages"]["kcoj_courtnet"] = {
            "count": 0,
            "status": "skipped",
            "reason": "no_party_searches_from_notices",
        }

    # e) GIS — smaller default limit
    gis_leads = await _run_stage(
        browser,
        "ky_state_gis",
        {"counties": counties, "limit": gis_limit},
        summary,
        stage_key="ky_state_gis",
    )

    # f) PVA enrichment
    logger.info("[pre-mls] PVA enrichment")
    pva_leads = await _run_pva_enrichment(
        browser, counties, notice_leads, kcoj_leads, gis_leads, limit_per_source, summary,
    )

    # f2) eCCLIX day-pass — clerk deeds/wills/mortgages for known addresses
    ecclix_leads: list[Lead] = []
    if params.get("run_ecclix", True) and settings.ecclix_username and settings.ecclix_password:
        ecclix_limit = params.get("ecclix_limit", settings.ecclix_batch_threshold)
        ecclix_leads = await _run_stage(
            browser,
            "ecclix_batch",
            {
                "mode": params.get("ecclix_mode", "lp_recent"),
                "download_documents": params.get("ecclix_download", True),
                "days_back": params.get("ecclix_days_back", 30),
                "max_documents_per_county": params.get(
                    "ecclix_max_per_county", min(15, ecclix_limit // 5 or 15)
                ),
                "counties": params.get("ecclix_counties") or settings.ecclix_county_list or None,
            },
            summary,
            stage_key="ecclix_batch",
        )
    else:
        summary["stages"]["ecclix_batch"] = {
            "count": 0,
            "status": "skipped",
            "reason": "no_ecclix_credentials_or_run_ecclix_false",
        }

    # g) Cross-reference court-like leads with PVA + GIS property data
    logger.info("[pre-mls] Cross-reference")
    property_leads = pva_leads + gis_leads
    court_like = _court_like_leads(notice_leads, kcoj_leads, mc_leads, tax_leads)

    enriched_notice = cross_reference_leads(notice_leads, property_leads)
    enriched_kcoj = cross_reference_leads(kcoj_leads, property_leads)
    enriched_mc = cross_reference_leads(mc_leads, property_leads)
    enriched_tax = cross_reference_leads(tax_leads, property_leads)

    summary["stages"]["cross_reference"] = {
        "court_like_input": len(court_like),
        "notice_enriched": sum(1 for l in enriched_notice if l.property_address),
        "kcoj_enriched": sum(1 for l in enriched_kcoj if l.property_address),
        "mc_enriched": sum(1 for l in enriched_mc if l.property_address),
        "tax_enriched": sum(1 for l in enriched_tax if l.property_address),
    }

    # h) Merge, dedupe, score, persist
    all_leads: list[Lead] = (
        enriched_notice
        + enriched_kcoj
        + pva_leads
        + gis_leads
        + enriched_mc
        + enriched_tax
        + ecclix_leads
    )

    seen_hashes: set[str] = set()
    deduped: list[Lead] = []
    for lead in all_leads:
        if lead.dedupe_hash not in seen_hashes:
            seen_hashes.add(lead.dedupe_hash)
            deduped.append(lead)

    summary["stages"]["dedup"] = {"before": len(all_leads), "after": len(deduped)}

    scored = score_leads(deduped)
    summary["total_leads"] = len(scored)
    summary["hot_leads"] = sum(1 for l in scored if (l.hot_score or 0) >= 60)

    logger.info("[pre-mls] Persisting %d leads", len(scored))
    try:
        from app.storage.supabase_client import upsert_leads
        persisted = await upsert_leads(scored)
        summary["stages"]["persist"] = {"count": persisted, "status": "ok"}
    except Exception as exc:
        logger.error("[pre-mls] Persist failed: %s", exc)
        summary["stages"]["persist"] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # POST-PERSIST: Automated GIS Address Enrichment                    #
    # ------------------------------------------------------------------ #
    logger.info("[pre-mls] Post-Persist: Executing automated GIS Address Enrichment backfills...")
    try:
        from app.pipeline.gis_address_enrichment import enrich_all_counties_gis
        gis_results = await enrich_all_counties_gis()
        summary["stages"]["gis_enrichment"] = gis_results
    except Exception as exc:
        logger.error("[pre-mls] Post-Persist GIS Enrichment failed: %s", exc)
        summary["stages"]["gis_enrichment"] = {"error": str(exc)}

    logger.info(
        "[pre-mls] Complete: %d leads, %d hot (score≥60)",
        summary["total_leads"], summary["hot_leads"],
    )
    return scored, summary
