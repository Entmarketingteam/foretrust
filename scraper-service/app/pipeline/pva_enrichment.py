"""Batch PVA enrichment + Supabase join for tax leads."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.pipeline.investment_scorer import score_from_lead_data
from app.pipeline.property_address import (
    is_valid_street_address,
    sanitize_lead_address,
)
from app.pipeline.underwriting import condition_adjusted_value, offer_band

logger = logging.getLogger(__name__)

PVA_FIELDS = (
    "property_address",
    "parcel_number",
    "year_built",
    "building_sqft",
    "assessed_value",
    "last_sale_price",
    "last_sale_date",
    "last_sale_year",
    "mailing_address",
    "homestead_exemption",
    "owner_occupied",
    "tax_delinquent",
    "land_use",
    "bedrooms",
    "bathrooms",
)


def _parse_sale_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", str(date_str))
    return int(m.group(1)) if m else None


def apply_pva_data(lead: dict[str, Any], pva: dict[str, Any]) -> dict[str, Any]:
    """Merge PVA detail into lead dict + re-score."""
    out = sanitize_lead_address({**lead})
    for field in PVA_FIELDS:
        val = pva.get(field)
        if val is not None and val != "" and not out.get(field):
            out[field] = val

    if pva.get("last_sale_date") and not out.get("last_sale_year"):
        out["last_sale_year"] = _parse_sale_year(str(pva.get("last_sale_date")))

    if pva.get("assessed_value") and not out.get("estimated_value"):
        out["estimated_value"] = pva["assessed_value"]

    adj = condition_adjusted_value(
        float(pva.get("assessed_value") or out.get("estimated_value") or 0) or None,
        year_built=out.get("year_built"),
        homestead_exemption=pva.get("homestead_exemption"),
    )
    out["condition_adjusted"] = adj
    scores = score_from_lead_data(out)
    out["investment_scores"] = scores
    strat = scores.get("primary_creative_play") or "wholesale_cash"
    out["offer_band"] = offer_band(adj.get("adjusted_value"), strategy=strat)
    out["pva_enriched"] = True
    out["pva_enriched_at"] = datetime.now(timezone.utc).isoformat()
    return out


async def fetch_leads_for_pva(
    *,
    county: str | None = None,
    source_keys: list[str] | None = None,
    limit: int = 2000,
    require_missing_pva: bool = True,
) -> list[dict[str, Any]]:
    from app.pipeline.deal_package import lead_from_supabase_row
    from app.storage.supabase_client import _get_client

    client = _get_client()
    if not client:
        return []

    keys = source_keys or ["ecclix_csv_import", "ecclix_batch"]
    juris = f"KY-{county.title()}" if county else None
    rows: list[dict] = []

    for sk in keys:
        q = client.table("ft_leads").select("*").eq("source_key", sk)
        if juris:
            q = q.ilike("jurisdiction", f"%{county}%")
        q = q.order("hot_score", desc=True).limit(limit)
        try:
            rows.extend(q.execute().data or [])
        except Exception as exc:
            logger.warning("fetch %s: %s", sk, exc)

    leads = [sanitize_lead_address(lead_from_supabase_row(r)) for r in rows]
    if require_missing_pva:
        leads = [
            l for l in leads
            if not (l.get("raw_payload") or {}).get("pva_enriched")
            and not l.get("year_built")
        ]
    return leads[:limit]


async def enrich_leads_with_pva(
    browser,
    leads: list[dict[str, Any]],
    *,
    county: str,
    max_enrich: int = 500,
    workers_delay: float = 2.5,
) -> tuple[list[dict[str, Any]], int]:
    """Address-first, then parcel, then owner name lookups."""
    from app.browser import create_context, human_delay
    from app.connectors.registry import get_connector

    key = f"{county.lower()}_pva"
    try:
        conn = get_connector(key)
    except KeyError:
        logger.error("No PVA connector: %s", key)
        return leads, 0

    enriched_count = 0
    async with create_context(browser) as ctx:
        page = await ctx.new_page()
        for i, lead in enumerate(leads[:max_enrich]):
            addr = (lead.get("property_address") or "").strip()
            parcel = (lead.get("parcel_number") or "").strip()
            owner = (lead.get("owner_name") or "").strip()
            pva_data = None

            pva_data = None
            try:
                if is_valid_street_address(addr):
                    logger.info("[pva] %d address: %s", i + 1, addr[:50])
                    rec = await conn._lookup(page, addr, search_by="address")
                elif parcel:
                    logger.info("[pva] %d parcel: %s", i + 1, parcel[:30])
                    rec = await conn._lookup(page, parcel, search_by="parcel")
                else:
                    rec = None

                if not rec and owner:
                    logger.info("[pva] %d owner: %s", i + 1, owner[:40])
                    rec = await conn._lookup(page, owner, search_by="name")

                pva_data = rec.data if rec else None
            except Exception as exc:
                logger.warning("[pva] lookup failed lead %d: %s", i + 1, exc)

            if pva_data:
                merged = apply_pva_data(lead, pva_data)
                leads[i] = merged
                enriched_count += 1

            await human_delay(workers_delay, workers_delay + 1.0)

    return leads, enriched_count


async def persist_pva_enrichment(leads: list[dict[str, Any]]) -> int:
    """Write PVA fields back to ft_leads."""
    from app.storage.supabase_client import _get_client

    client = _get_client()
    if not client:
        return 0

    updated = 0
    for lead in leads:
        if not lead.get("pva_enriched") or not lead.get("id"):
            continue
        payload = lead.get("raw_payload") or {}
        if isinstance(payload, str):
            payload = {}
        payload = {
            **payload,
            "pva_enriched": True,
            "pva_enriched_at": lead.get("pva_enriched_at"),
            "investment_scores": lead.get("investment_scores"),
            "condition_adjusted": lead.get("condition_adjusted"),
            "offer_band": lead.get("offer_band"),
            "homestead_exemption": lead.get("homestead_exemption"),
            "last_sale_price": lead.get("last_sale_price"),
            "last_sale_year": lead.get("last_sale_year"),
            "last_sale_date": lead.get("last_sale_date"),
        }
        patch: dict[str, Any] = {
            "raw_payload": payload,
            "hot_score": (lead.get("investment_scores") or {}).get("pre_mls_score")
            or lead.get("hot_score"),
        }
        if lead.get("property_address") and is_valid_street_address(lead["property_address"]):
            patch["property_address"] = lead["property_address"]
        if lead.get("mailing_address"):
            patch["mailing_address"] = lead["mailing_address"]
        if lead.get("parcel_number"):
            patch["parcel_number"] = lead["parcel_number"]
        if lead.get("year_built"):
            patch["year_built"] = int(lead["year_built"])
        if lead.get("building_sqft"):
            patch["building_sqft"] = int(lead["building_sqft"])
        if lead.get("estimated_value"):
            patch["estimated_value"] = float(lead["estimated_value"])

        try:
            client.table("ft_leads").update(patch).eq("id", lead["id"]).execute()
            updated += 1
        except Exception as exc:
            logger.warning("PVA persist %s: %s", lead.get("id"), exc)

    logger.info("[pva] persisted %d/%d enriched leads", updated, len(leads))
    return updated
