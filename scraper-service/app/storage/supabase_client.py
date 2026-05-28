"""Supabase storage client for ft_leads and ft_lead_source_runs.

Uses postgrest-py via the supabase-py SDK. Handles dedup by hash
(ON CONFLICT DO NOTHING on the unique constraint).
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOGIN_JUNK = re.compile(r"login|password|ecclix central|walkthrough", re.I)
_ECCLIX_LOGIN_JUNK = re.compile(
    r"eCCLIX|Login|Subscribe|Privacy Policy|Getting Started|Public Sign-Up|"
    r"payment\s+walkthrough|welcome to ecclix|remember\s+me|forgot\s+password",
    re.I,
)
_NAV_ROW_MARKERS = (
    "NEW SEARCH",
    "NAVIGATION:",
    "INS#/DATE",
    "PARTY1/PARTY2",
    "WELCOME",
    "LOGOUT",
)

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


def _lead_blob_for_junk_check(lead: Lead) -> str:
    rp = lead.raw_payload if isinstance(lead.raw_payload, dict) else {}
    return " ".join(
        str(p)
        for p in (
            lead.owner_name,
            lead.property_address,
            rp.get("row_text"),
            rp.get("legal_description"),
            rp.get("grantor"),
            rp.get("grantee"),
            rp.get("instrument_type"),
        )
        if p
    )


def _lead_is_persistable(lead: Lead) -> bool:
    from app.connectors.residential.ecclix_portal import is_junk_portal_row

    rp = lead.raw_payload if isinstance(lead.raw_payload, dict) else {}
    owner = lead.owner_name or rp.get("grantor") or ""
    addr = lead.property_address or ""
    blob = _lead_blob_for_junk_check(lead)
    if is_junk_portal_row(blob, rp):
        return False
    if _LOGIN_JUNK.search(blob) or _ECCLIX_LOGIN_JUNK.search(blob):
        return False
    if any(marker in blob.upper() for marker in _NAV_ROW_MARKERS):
        return False
    if lead.source_key == "ecclix_batch":
        inst = ((rp.get("instrument_type") or "")).strip().upper()
        book = str(rp.get("book") or "").strip()
        page = str(rp.get("page") or "").strip()
        if inst and _LOGIN_JUNK.search(inst):
            return False
        if owner and len(owner) > 200:
            return False
        # Instrument identity rows need book+page; skip nav blobs with no identity
        if inst and not (book and page):
            return False
        if not book and not page and not addr and not owner:
            return False
    return True


def lookup_lead_id_by_book_page(
    county: str,
    book: str,
    page: str,
    *,
    source_key: str = "ecclix_batch",
) -> str | None:
    """Resolve ft_leads.id for an instrument by county + book/page (case_id)."""
    book = str(book or "").strip()
    page = str(page or "").strip()
    if not book or not page:
        return None
    client = _get_client()
    if not client:
        return None
    county_title = county.strip().title().replace("Ky-", "KY-")
    if county_title.upper().startswith("KY-"):
        jurisdiction = county_title.upper()
    else:
        jurisdiction = f"KY-{county_title}"
    case_id = f"{book}/{page}"
    try:
        result = (
            client.table("ft_leads")
            .select("id")
            .eq("source_key", source_key)
            .eq("jurisdiction", jurisdiction)
            .eq("case_id", case_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0]["id"] if rows else None
    except Exception as exc:
        logger.warning("lead lookup %s %s/%s: %s", county, book, page, exc)
        return None


def _link_clerk_docs_for_ecclix_leads(leads: list[Lead]) -> None:
    """Attach lead_id on clerk rows matching freshly upserted instrument leads."""
    client = _get_client()
    if not client:
        return
    specs: list[tuple[str, str, str, str]] = []
    for lead in leads:
        if lead.source_key != "ecclix_batch" or not lead.dedupe_hash:
            continue
        rp = lead.raw_payload if isinstance(lead.raw_payload, dict) else {}
        book = str(rp.get("book") or "").strip()
        page = str(rp.get("page") or "").strip()
        if not book or not page:
            continue
        county = (rp.get("county") or lead.jurisdiction or "").replace("KY-", "").strip()
        specs.append((county.title(), book, page, lead.dedupe_hash))
    if not specs:
        return
    hashes = list({s[3] for s in specs})
    try:
        result = (
            client.table("ft_leads")
            .select("id, dedupe_hash")
            .eq("source_key", "ecclix_batch")
            .in_("dedupe_hash", hashes)
            .execute()
        )
        id_by_hash = {r["dedupe_hash"]: r["id"] for r in (result.data or [])}
    except Exception as exc:
        logger.warning("clerk link lead fetch failed: %s", exc)
        return
    for county, book, page, dedupe_hash in specs:
        lead_id = id_by_hash.get(dedupe_hash)
        if not lead_id:
            continue
        try:
            client.table("ft_clerk_documents").update({"lead_id": lead_id}).eq(
                "source_key", "ecclix_batch"
            ).eq("county", county).eq("book", book).eq("page", page).is_(
                "lead_id", "null"
            ).execute()
        except Exception as exc:
            logger.warning(
                "clerk link %s %s/%s: %s", county, book, page, exc
            )


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

    clean = [lead for lead in leads if _lead_is_persistable(lead)]
    if len(clean) < len(leads):
        logger.info(
            "Supabase: dropped %d junk/unpersistable leads",
            len(leads) - len(clean),
        )
    rows = [_lead_to_row(lead) for lead in clean]
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
    if inserted:
        _link_clerk_docs_for_ecclix_leads(clean)
    return inserted


async def upsert_leads(leads: list[Lead]) -> int:
    """Batch upsert ft_leads (alias for ``insert_leads`` — used by pipeline orchestrators)."""
    return await insert_leads(leads)


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


# Match ft_leads VARCHAR limits (see supabase/migrations)
_VARCHAR_LIMITS: dict[str, int] = {
    "source_key": 100,
    "jurisdiction": 100,
    "lead_type": 50,
    "owner_name": 255,
    "city": 100,
    "state": 50,
    "postal_code": 20,
    "parcel_number": 100,
    "case_id": 100,
}


def _clip(field: str, value: Any) -> Any:
    if value is None or field not in _VARCHAR_LIMITS:
        return value
    s = str(value).strip()
    if "login.aspx" in s.lower() or ("ecclix" in s.lower() and "log in" in s.lower()):
        return None
    max_len = _VARCHAR_LIMITS[field]
    return s[:max_len] if len(s) > max_len else s


def _lead_to_row(lead: Lead) -> dict[str, Any]:
    """Convert a Lead model to a Supabase row dict."""
    from app.pipeline.property_address import normalize_property_address

    legal = ""
    rp = lead.raw_payload
    if isinstance(rp, dict):
        legal = str(rp.get("legal_description") or "")
    property_address = normalize_property_address(
        lead.property_address,
        legal=legal,
    )

    return {
        "organization_id": DEFAULT_ORG_ID,
        "source_key": _clip("source_key", lead.source_key),
        "vertical": lead.vertical.value,
        "jurisdiction": _clip("jurisdiction", lead.jurisdiction),
        "lead_type": _clip("lead_type", lead.lead_type.value),
        "owner_name": _clip("owner_name", lead.owner_name),
        "mailing_address": lead.mailing_address,
        "property_address": property_address,
        "city": _clip("city", lead.city),
        "state": _clip("state", lead.state),
        "postal_code": _clip("postal_code", lead.postal_code),
        "parcel_number": _clip("parcel_number", lead.parcel_number),
        "building_sqft": lead.building_sqft,
        "unit_count": lead.unit_count,
        "year_built": lead.year_built,
        "case_id": _clip("case_id", lead.case_id),
        "case_filed_date": lead.case_filed_date.isoformat() if lead.case_filed_date else None,
        "estimated_value": lead.estimated_value,
        "raw_payload": lead.raw_payload,
        "dedupe_hash": lead.dedupe_hash,
        "hot_score": lead.hot_score,
        "scraped_at": lead.scraped_at.isoformat(),
    }
