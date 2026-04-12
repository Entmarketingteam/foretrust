"""Full-pipeline orchestrator.

Chains all free KY data sources end-to-end for maximum property intelligence.
No paid APIs required. Zero stone unturned.

Pipeline stages:
  1. KCOJ CourtNet     — probate, divorce, foreclosure case filings (daily signal)
  2. KY State GIS      — parcel discovery for all target counties
  3. County PVA        — full property detail per parcel: sqft, yr built, assessed value,
                         mailing address, sales history, tax payment status
  4. Master Commissioner — foreclosure auction sale listings (urgent/time-sensitive)
  5. Delinquent Tax    — multi-year unpaid tax records (highest distress)
  6. Legal Notices     — newspaper + RSS legal notice monitoring
  7. Cross-reference   — match KCOJ names → PVA property records
  8. Signal stacking   — detect leads with multiple distress signals on same parcel
  9. Hot score         — composite scoring (0-100) for prioritization
 10. Persist           — write to Supabase via storage layer

WHY each source matters:
  KCOJ:          Owner's name is in a court filing → they HAVE to act on it.
  GIS:           Discovers vacant/large parcels with no recent activity.
  PVA:           Mailing address (where to send the offer) + assessed value (your ceiling).
  MC sales:      Sale date is scheduled → maximum urgency.
  Delinquent tax:Owner hasn't paid taxes in years → financially distressed, often absent.
  Legal notices: Earliest possible signal — captured the moment it's published.
  Cross-ref:     KCOJ + PVA match gives you the WHY (court case) + WHERE (property address)
                 + HOW MUCH (assessed value) in a single enriched lead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser

from app.models import Lead
from app.pipeline.enrich import cross_reference_leads
from app.pipeline.distress_scorer import score_leads

logger = logging.getLogger(__name__)

# Mapping: county name → PVA connector source_key
# Used to route GIS parcel addresses to the right county PVA connector
COUNTY_PVA_MAP: dict[str, str] = {
    "fayette": "fayette_pva",
    "scott": "scott_pva",
    "oldham": "oldham_pva",
    "clark": "clark_pva",
    "madison": "madison_pva",
    "woodford": "woodford_pva",
    "jessamine": "jessamine_pva",
    "jefferson": "jefferson_pva",
}

DEFAULT_COUNTIES = list(COUNTY_PVA_MAP.keys())


async def run_full_pipeline(
    browser: Browser,
    params: dict[str, Any] | None = None,
) -> tuple[list[Lead], dict[str, Any]]:
    """Execute the complete free-source pipeline.

    Returns (leads, run_summary) where run_summary contains counts per stage.
    Persists all leads to Supabase.
    """
    params = params or {}
    counties = params.get("counties", DEFAULT_COUNTIES)
    limit_per_source = params.get("limit_per_source", 100)

    summary: dict[str, Any] = {
        "counties": counties,
        "stages": {},
    }

    from app.connectors.registry import get_connector

    # ------------------------------------------------------------------ #
    # STAGE 1: KCOJ — court case filings (probate, divorce, foreclosure)  #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 1: KCOJ court cases")
    kcoj_leads: list[Lead] = []
    try:
        kcoj_conn = get_connector("kcoj_courtnet")()
        kcoj_leads, kcoj_run = await kcoj_conn.run(
            browser,
            params={"counties": [c.title() for c in counties], "limit": limit_per_source},
        )
        summary["stages"]["kcoj"] = {"count": len(kcoj_leads), "status": kcoj_run.status.value}
    except Exception as exc:
        logger.error("[pipeline] KCOJ stage failed: %s", exc)
        summary["stages"]["kcoj"] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # STAGE 2: GIS parcel discovery                                       #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 2: GIS parcel discovery")
    gis_leads: list[Lead] = []
    try:
        gis_conn = get_connector("ky_state_gis")()
        gis_leads, gis_run = await gis_conn.run(
            browser,
            params={"counties": counties, "limit": limit_per_source},
        )
        summary["stages"]["gis"] = {"count": len(gis_leads), "status": gis_run.status.value}
    except Exception as exc:
        logger.error("[pipeline] GIS stage failed: %s", exc)
        summary["stages"]["gis"] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # STAGE 3: PVA enrichment — route each county's parcels to its PVA   #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 3: PVA enrichment for %d GIS parcels", len(gis_leads))
    pva_leads: list[Lead] = []

    # Group GIS leads by county
    by_county: dict[str, list[str]] = {}
    for lead in gis_leads:
        county_raw = (lead.jurisdiction or "").replace("KY-", "").lower()
        addr = lead.property_address
        if county_raw and addr:
            by_county.setdefault(county_raw, []).append(addr)

    # Also route KCOJ name lookups to PVA
    kcoj_names_by_county: dict[str, list[str]] = {}
    for lead in kcoj_leads:
        county_raw = (lead.jurisdiction or "").replace("KY-", "").lower()
        if county_raw and lead.owner_name:
            kcoj_names_by_county.setdefault(county_raw, []).append(lead.owner_name)

    for county_key, pva_source_key in COUNTY_PVA_MAP.items():
        if county_key not in counties and county_key.title() not in counties:
            continue

        addresses = by_county.get(county_key, [])
        names = kcoj_names_by_county.get(county_key, [])

        if not addresses and not names:
            continue

        try:
            pva_conn = get_connector(pva_source_key)()
            leads, run = await pva_conn.run(
                browser,
                params={
                    "addresses": addresses[:limit_per_source],
                    "names": names[:50],  # Cap name lookups to avoid overload
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
                "[pipeline] %s: %d leads from %d addresses + %d names",
                pva_source_key, len(leads), len(addresses), len(names),
            )
        except Exception as exc:
            logger.warning("[pipeline] PVA stage %s failed: %s", pva_source_key, exc)
            summary["stages"][pva_source_key] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # STAGE 4: Master Commissioner — foreclosure auction listings         #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 4: Master Commissioner sale listings")
    mc_leads: list[Lead] = []
    try:
        mc_conn = get_connector("ky_master_commissioner")()
        mc_leads, mc_run = await mc_conn.run(
            browser,
            params={"counties": [c.title() for c in counties], "limit": limit_per_source},
        )
        summary["stages"]["ky_master_commissioner"] = {
            "count": len(mc_leads), "status": mc_run.status.value
        }
    except Exception as exc:
        logger.warning("[pipeline] MC stage failed: %s", exc)
        summary["stages"]["ky_master_commissioner"] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # STAGE 5: Delinquent tax lists                                       #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 5: Delinquent tax lists")
    tax_leads: list[Lead] = []
    try:
        tax_conn = get_connector("ky_delinquent_tax")()
        tax_leads, tax_run = await tax_conn.run(
            browser,
            params={"counties": counties, "limit": limit_per_source * 2},  # Higher limit for tax lists
        )
        summary["stages"]["ky_delinquent_tax"] = {
            "count": len(tax_leads), "status": tax_run.status.value
        }
    except Exception as exc:
        logger.warning("[pipeline] Delinquent tax stage failed: %s", exc)
        summary["stages"]["ky_delinquent_tax"] = {"count": 0, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # STAGE 6: Legal notices (newspaper + Google Alerts RSS)              #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 6: Legal notices")
    notice_leads: list[Lead] = []
    try:
        notice_conn = get_connector("legal_notices")()
        notice_leads, notice_run = await notice_conn.run(browser, params={})
        summary["stages"]["legal_notices"] = {
            "count": len(notice_leads), "status": notice_run.status.value
        }
    except Exception as exc:
        logger.warning("[pipeline] Legal notices stage failed: %s", exc)
        summary["stages"]["legal_notices"] = {"count": 0, "status": "error"}

    # ------------------------------------------------------------------ #
    # STAGE 7: Cross-reference — match KCOJ names → PVA property data    #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 7: Cross-referencing KCOJ ↔ PVA")
    all_property_leads = pva_leads + gis_leads  # Both have address + parcel data
    enriched_kcoj = cross_reference_leads(kcoj_leads, all_property_leads)

    # Also enrich MC and delinquent tax leads with PVA property data
    enriched_mc = cross_reference_leads(mc_leads, all_property_leads)
    enriched_tax = cross_reference_leads(tax_leads, all_property_leads)

    summary["stages"]["cross_reference"] = {
        "kcoj_enriched": sum(1 for l in enriched_kcoj if l.property_address),
        "mc_enriched": sum(1 for l in enriched_mc if l.property_address),
        "tax_enriched": sum(1 for l in enriched_tax if l.property_address),
    }

    # ------------------------------------------------------------------ #
    # STAGE 8+9: Merge, deduplicate, score                                #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 8: Merge + deduplicate")
    all_leads: list[Lead] = (
        enriched_kcoj +
        pva_leads +
        gis_leads +
        enriched_mc +
        enriched_tax +
        notice_leads
    )

    # Deduplicate by dedupe_hash
    seen_hashes: set[str] = set()
    deduped: list[Lead] = []
    for lead in all_leads:
        if lead.dedupe_hash not in seen_hashes:
            seen_hashes.add(lead.dedupe_hash)
            deduped.append(lead)

    summary["stages"]["dedup"] = {
        "before": len(all_leads),
        "after": len(deduped),
    }

    logger.info("[pipeline] Stage 9: Scoring %d leads", len(deduped))
    scored = score_leads(deduped)

    summary["total_leads"] = len(scored)
    summary["hot_leads"] = sum(1 for l in scored if (l.hot_score or 0) >= 60)

    # ------------------------------------------------------------------ #
    # STAGE 10: Persist to Supabase                                       #
    # ------------------------------------------------------------------ #
    logger.info("[pipeline] Stage 10: Persisting %d leads to Supabase", len(scored))
    try:
        from app.storage.supabase_client import upsert_leads
        persisted = await upsert_leads(scored)
        summary["stages"]["persist"] = {"count": persisted, "status": "ok"}
    except Exception as exc:
        logger.error("[pipeline] Persist stage failed: %s", exc)
        summary["stages"]["persist"] = {"count": 0, "status": "error", "error": str(exc)}

    logger.info(
        "[pipeline] Complete: %d total leads, %d hot (score≥60)",
        summary["total_leads"], summary["hot_leads"],
    )
    return scored, summary
