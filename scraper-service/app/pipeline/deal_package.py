"""Build ranked pre-MLS deal packages: score → PVA enrich → report."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.investment_scorer import is_human_owner, score_from_lead_data

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports" / "best-deals"


def lead_from_supabase_row(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten ft_leads row for scoring."""
    payload = row.get("raw_payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    merged = {
        **payload,
        "id": row.get("id"),
        "source_key": row.get("source_key"),
        "owner_name": row.get("owner_name") or payload.get("owner_name"),
        "property_address": row.get("property_address") or payload.get("property_address"),
        "parcel_number": row.get("parcel_number") or payload.get("map_id"),
        "estimated_value": row.get("estimated_value") or payload.get("amount_due"),
        "year_built": row.get("year_built"),
        "building_sqft": row.get("building_sqft"),
        "lead_type": row.get("lead_type"),
        "hot_score": row.get("hot_score"),
    }
    merged["investment_scores"] = score_from_lead_data(merged)
    return merged


async def fetch_distress_leads(
    *,
    source_keys: list[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    from app.storage.supabase_client import _get_client

    keys = source_keys or ["ecclix_csv_import", "ecclix_batch"]
    client = _get_client()
    if not client:
        return []

    out: list[dict[str, Any]] = []
    for sk in keys:
        try:
            resp = (
                client.table("ft_leads")
                .select("*")
                .eq("source_key", sk)
                .order("hot_score", desc=True)
                .limit(limit)
                .execute()
            )
            for row in resp.data or []:
                out.append(lead_from_supabase_row(row))
        except Exception as exc:
            logger.warning("fetch leads %s: %s", sk, exc)
    return out


def rank_deals(leads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket leads for outreach tracks."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "pre_mls_homebuyer": [],
        "tax_delinquent_human": [],
        "short_sale": [],
        "fha_203k": [],
        "creative_finance": [],
        "wholesale": [],
        "stacked_signals": [],
    }
    for lead in leads:
        scores = lead.get("investment_scores") or {}
        human = is_human_owner(lead.get("owner_name"))
        due = float(lead.get("amount_due") or 0)
        if not human:
            buckets["wholesale"].append(lead)
            continue
        if due >= 1500 and lead.get("property_address"):
            buckets["tax_delinquent_human"].append(lead)
        if scores.get("pre_mls_score", 0) >= 55:
            buckets["pre_mls_homebuyer"].append(lead)
        if scores.get("short_sale_score", 0) >= 70:
            buckets["short_sale"].append(lead)
        if scores.get("fha_203k_score", 0) >= 60:
            buckets["fha_203k"].append(lead)
        if scores.get("creative_score", 0) >= 70:
            buckets["creative_finance"].append(lead)
        if scores.get("wholesale_score", 0) >= 70:
            buckets["wholesale"].append(lead)
        if lead.get("lp_active") and due >= 500:
            buckets["stacked_signals"].append(lead)

    for key in buckets:
        if key == "tax_delinquent_human":
            buckets[key].sort(key=lambda x: -(float(x.get("amount_due") or 0)))
        else:
            buckets[key].sort(
                key=lambda x: (
                    -(x.get("investment_scores") or {}).get("pre_mls_score", 0),
                    -(float(x.get("amount_due") or 0)),
                ),
            )
    return buckets


async def enrich_with_pva(
    browser,
    leads: list[dict[str, Any]],
    *,
    county: str = "scott",
    max_enrich: int = 35,
) -> list[dict[str, Any]]:
    """qPublic owner search for top leads missing PVA fields."""
    from app.connectors.registry import get_connector

    key = f"{county.lower()}_pva"
    try:
        conn = get_connector(key)()
    except KeyError:
        logger.warning("No PVA connector for %s", county)
        return leads

    to_enrich = [
        l for l in leads
        if is_human_owner(l.get("owner_name"))
        and not l.get("year_built")
    ][:max_enrich]

    if not to_enrich:
        return leads

    names = list({l["owner_name"] for l in to_enrich if l.get("owner_name")})
    params = {"names": names, "limit": max_enrich}
    try:
        raw = await conn.fetch(browser, params)
        by_owner: dict[str, dict] = {}
        for rec in raw:
            d = rec.data
            on = (d.get("owner_name") or "").upper()
            if on and on not in by_owner:
                by_owner[on] = d
        for lead in leads:
            on = (lead.get("owner_name") or "").upper()
            pva = by_owner.get(on)
            if not pva:
                continue
            for field in (
                "property_address", "parcel_number", "year_built",
                "building_sqft", "assessed_value", "last_sale_price",
                "last_sale_year", "mailing_address", "tax_delinquent",
            ):
                if pva.get(field) and not lead.get(field):
                    lead[field] = pva.get(field)
            if pva.get("assessed_value"):
                lead["estimated_value"] = pva["assessed_value"]
            lead["pva_enriched"] = True
            lead["investment_scores"] = score_from_lead_data(lead)
    except Exception as exc:
        logger.error("PVA enrich failed: %s", exc)
    return leads


def write_deal_report(
    buckets: dict[str, list[dict[str, Any]]],
    *,
    out_dir: Path | None = None,
) -> Path:
    out_dir = out_dir or EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    md_path = out_dir / f"best-deals-{stamp}.md"
    json_path = out_dir / f"best-deals-{stamp}.json"

    lines = [
        "# Pre-MLS Best Deals — Scott County KY",
        f"Generated: {stamp} UTC",
        "",
        "Use **pre_mls_homebuyer** + **short_sale** for FHA 203k / conventional owner-occupant.",
        "Use **wholesale** for LLC/commercial or assignment plays.",
        "",
    ]

    sections = [
        ("tax_delinquent_human", "Human owners — delinquent tax (call + PVA + LP check)"),
        ("pre_mls_homebuyer", "Owner-occupant — FHA 203k / conventional (pre-MLS)"),
        ("short_sale", "Short sale candidates (LP + bank + human owner)"),
        ("fha_203k", "FHA 203k renovation (older home + equity)"),
        ("creative_finance", "Subject-to / creative (low equity, recent loan)"),
        ("stacked_signals", "Stacked: tax delinquent + other distress"),
        ("wholesale", "Wholesale / entity-owned"),
    ]

    export_data: dict[str, Any] = {}
    for key, title in sections:
        items = buckets.get(key, [])[:25]
        export_data[key] = items
        lines.append(f"## {title} ({len(items)} shown)")
        lines.append("")
        if not items:
            lines.append("_None in this bucket yet — run LP scrape or PVA enrich._")
            lines.append("")
            continue
        lines.append("| Score | Owner | Address | Tax due | Strategy | Map ID |")
        lines.append("|------:|-------|---------|--------:|----------|--------|")
        for item in items:
            sc = item.get("investment_scores") or {}
            lines.append(
                f"| {sc.get('pre_mls_score', 0)} "
                f"| {item.get('owner_name', '')[:40]} "
                f"| {item.get('property_address', '')[:35]} "
                f"| ${item.get('amount_due') or item.get('estimated_value') or 0:,.0f} "
                f"| {sc.get('short_sale_score', 0)}/{sc.get('fha_203k_score', 0)} "
                f"| {item.get('parcel_number', '')} |"
            )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps(export_data, indent=2, default=str), encoding="utf-8")
    logger.info("Deal report: %s", md_path)
    return md_path


async def build_best_deals_package(
    browser,
    *,
    enrich_pva: bool = True,
    county: str = "scott",
    pva_limit: int = 35,
) -> dict[str, Any]:
    """Full pipeline for operator."""
    leads = await fetch_distress_leads()
    if enrich_pva and browser:
        leads = await enrich_with_pva(browser, leads, county=county, max_enrich=pva_limit)
    buckets = rank_deals(leads)
    report_path = write_deal_report(buckets)
    return {
        "total_leads": len(leads),
        "report_md": str(report_path),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "top_pre_mls": buckets.get("pre_mls_homebuyer", [])[:10],
        "top_short_sale": buckets.get("short_sale", [])[:10],
    }
