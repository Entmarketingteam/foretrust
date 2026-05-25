"""Unified signal intel — LP, probate, code violations, water; then email digest."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.models import Lead

logger = logging.getLogger(__name__)


async def fetch_all_signals(browser, params: dict[str, Any]) -> list[Lead]:
    """Run every distress channel and return scored leads."""
    from app.connectors.registry import get_connector
    from app.pipeline.distress_scorer import score_leads
    counties = params.get("counties") or ["scott", "bourbon", "woodford", "franklin"]
    all_leads: list[Lead] = []

    # 1) eCCLIX — ALL lis pendens + code liens + probate instruments
    if params.get("run_ecclix", True):
        conn = get_connector("ecclix_batch")
        ecclix_params = {
            "mode": params.get("ecclix_mode", "signal_intel"),
            "counties": counties,
            "download_documents": params.get("download_documents", False),
            "full_extract": True,
            "max_pages": int(params.get("max_pages", 80)),
            "tax_year": int(params.get("tax_year", 2025)),
            "days_back": int(params.get("days_back", 365)),
        }
        raw = await conn.fetch(browser, ecclix_params)
        leads = score_leads([conn.parse(r) for r in raw])
        all_leads.extend(leads)
        logger.info("[signal_intel] ecclix: %d leads", len(leads))

    # 2) KCOJ — probate + civil foreclosure
    if params.get("run_kcoj", True):
        try:
            from app.connectors.registry import get_connector as gc

            kcoj = gc("kcoj_courtnet")
            raw = await kcoj.fetch(
                browser,
                {
                    "bulk_legacy": True,
                    "counties": ["Scott", "Bourbon", "Woodford", "Franklin", "Fayette"],
                    "case_types": [
                        "P - Probate",
                        "D - Domestic Relations",
                        "CI - Civil",
                    ],
                    "limit": int(params.get("kcoj_limit", 40)),
                    "deep_scrape": True,
                },
            )
            leads = score_leads([kcoj.parse(r) for r in raw])
            all_leads.extend(leads)
            logger.info("[signal_intel] kcoj: %d leads", len(leads))
        except Exception as exc:
            logger.error("[signal_intel] kcoj failed: %s", exc)

    # 3) Legal notices RSS
    if params.get("run_legal_notices", True):
        try:
            ln = get_connector("legal_notices")
            raw = await ln.fetch(browser, {"limit": 30})
            leads = score_leads([ln.parse(r) for r in raw])
            all_leads.extend(leads)
            logger.info("[signal_intel] legal_notices: %d leads", len(leads))
        except Exception as exc:
            logger.warning("[signal_intel] legal_notices: %s", exc)

    # 4) Georgetown water GIS (+ optional FOIA CSV)
    if params.get("run_water", True):
        try:
            gw = get_connector("georgetown_water")
            raw = await gw.fetch(
                browser,
                {
                    "limit": 200,
                    "foia_import_path": params.get("water_foia_csv"),
                },
            )
            leads = score_leads([gw.parse(r) for r in raw])
            all_leads.extend(leads)
            logger.info("[signal_intel] water: %d leads", len(leads))
        except Exception as exc:
            logger.warning("[signal_intel] water: %s", exc)

    return all_leads


def leads_to_db_rows(leads: list[Lead]) -> list[dict[str, Any]]:
    return [
        {
            "source_key": l.source_key,
            "lead_type": l.lead_type.value if hasattr(l.lead_type, "value") else l.lead_type,
            "owner_name": l.owner_name,
            "property_address": l.property_address,
            "mailing_address": l.mailing_address,
            "city": l.city,
            "parcel_number": l.parcel_number,
            "case_id": l.case_id,
            "hot_score": l.hot_score,
            "raw_payload": l.raw_payload,
        }
        for l in leads
    ]


async def run_signal_intel_pipeline(browser, params: dict[str, Any]) -> dict[str, Any]:
    """Fetch → persist → bucket → email digest."""
    from app.notifications.digest_email import bucket_leads, send_digest_email
    from app.storage.supabase_client import insert_leads

    started = datetime.utcnow()
    leads = await fetch_all_signals(browser, params)
    persisted = await insert_leads(leads) if params.get("persist", True) else 0

    rows = leads_to_db_rows(leads)
    buckets = bucket_leads(rows)
    summary = (
        f"Run {started.isoformat()}Z — {len(leads)} leads, {persisted} new in Supabase. "
        f"LP={len(buckets.get('lis_pendens', []))} | "
        f"Probate={len(buckets.get('probate', []))} | "
        f"Code={len(buckets.get('code_violations', []))} | "
        f"Water={len(buckets.get('water_shutoff', []))}"
    )

    email_result = {}
    if params.get("send_email", True):
        email_result = await send_digest_email(buckets, run_summary=summary)

    return {
        "total_leads": len(leads),
        "persisted": persisted,
        "buckets": {k: len(v) for k, v in buckets.items()},
        "email": email_result,
        "summary": summary,
    }
