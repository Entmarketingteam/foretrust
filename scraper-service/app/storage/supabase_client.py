"""Supabase storage client for ft_leads and ft_lead_source_runs.

Uses postgrest-py via the supabase-py SDK. Handles dedup by hash
(ON CONFLICT DO NOTHING on the unique constraint).
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.models import Lead, SourceRun

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not settings.supabase_url:
        logger.error(
            "Supabase client init failed: SUPABASE_URL is not set. "
            "Add it to Doppler under the scraper-service config."
        )
        return None
    if not settings.supabase_service_role_key:
        logger.error(
            "Supabase client init failed: SUPABASE_SERVICE_ROLE_KEY is not set. "
            "Add it to Doppler under the scraper-service config."
        )
        return None
    try:
        from supabase import create_client
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        return _client
    except Exception as exc:
        logger.error(
            "Supabase client init failed: %s — check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Doppler.",
            exc,
        )
        return None


async def insert_leads(leads: list[Lead]) -> int:
    """Insert leads into ft_leads, skipping duplicates by dedupe_hash.

    Uses batch upsert to avoid N+1 round-trips.
    Returns the number of leads in the batch (actual new vs. conflict
    is handled server-side via ON CONFLICT).
    """
    client = _get_client()
    if not client:
        logger.warning("Supabase unavailable; leads not persisted")
        return 0

    rows = [_lead_to_row(lead) for lead in leads]
    if not rows:
        return 0

    inserted = 0
    # Batch in chunks of 500 to stay within payload limits
    chunk_size = 500
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        try:
            client.table("ft_leads").upsert(
                chunk,
                on_conflict="source_key,dedupe_hash",
                returning="minimal",
            ).execute()
            inserted += len(chunk)
        except Exception as exc:
            logger.warning("Batch upsert failed (chunk %d): %s", i // chunk_size, exc)

    logger.info("Supabase: upserted %d leads", inserted)
    return inserted


async def insert_source_run(run: SourceRun) -> None:
    """Insert a scraper run audit log entry."""
    client = _get_client()
    if not client:
        return

    row = {
        "source_key": run.source_key,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "records_found": run.records_found,
        "records_new": run.records_new,
        "error_message": run.error_message,
        "proxy_session_id": run.proxy_session_id,
    }
    try:
        client.table("ft_lead_source_runs").insert(row).execute()
    except Exception as exc:
        logger.warning("Failed to insert source run: %s", exc)


async def get_pending_ecclix_leads(threshold: int) -> list[dict[str, Any]]:
    """Get leads pending eCCLIX enrichment (have owner name but no deed data)."""
    client = _get_client()
    if not client:
        return []

    try:
        result = (
            client.table("ft_leads")
            .select("id, owner_name, property_address, jurisdiction")
            .is_("raw_payload->>ecclix_enriched", "null")
            .not_.is_("property_address", "null")
            .order("hot_score", desc=True)
            .limit(threshold)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Failed to fetch pending eCCLIX leads: %s", exc)
        return []


async def list_source_runs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent scraper run audit entries."""
    client = _get_client()
    if not client:
        return []
    try:
        result = (
            client.table("ft_lead_source_runs")
            .select("id, source_key, status, started_at, finished_at, records_found, records_new, error_message")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Failed to list source runs: %s", exc)
        return []


DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _lead_to_row(lead: Lead) -> dict[str, Any]:
    """Convert a Lead model to a Supabase row dict."""
    return {
        "organization_id": DEFAULT_ORG_ID,
        "source_key": lead.source_key,
        "vertical": lead.vertical.value,
        "jurisdiction": lead.jurisdiction,
        "lead_type": lead.lead_type.value,
        "owner_name": lead.owner_name,
        "mailing_address": lead.mailing_address,
        "property_address": lead.property_address,
        "city": lead.city,
        "state": lead.state,
        "postal_code": lead.postal_code,
        "parcel_number": lead.parcel_number,
        "building_sqft": lead.building_sqft,
        "unit_count": lead.unit_count,
        "year_built": lead.year_built,
        "case_id": lead.case_id,
        "case_filed_date": lead.case_filed_date.isoformat() if lead.case_filed_date else None,
        "estimated_value": lead.estimated_value,
        "raw_payload": lead.raw_payload,
        "dedupe_hash": lead.dedupe_hash,
        "hot_score": lead.hot_score,
        "scraped_at": lead.scraped_at.isoformat(),
    }
