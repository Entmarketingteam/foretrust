#!/usr/bin/env python3
"""Rebuild portal-intel filtered JSON from Supabase ft_leads (no eCCLIX browser)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.connectors.residential.ecclix_portal import is_junk_portal_row
from app.connectors.residential.ecclix_row_filters import hot_tier
from app.connectors.residential.ecclix_search_profiles import PROFILE_REFERENCE_META
from app.pipeline.investment_scorer import best_strategy, score_from_lead_data
from app.storage.supabase_client import _get_client

EXPORTS = ROOT / "exports" / "portal-intel"
SOURCE_KEYS = ("ecclix_batch", "ecclix_csv_import")
_LOGIN_JUNK = re.compile(r"login|password|ecclix|walkthrough", re.I)


def _parse_county(lead: dict, rp: dict) -> str:
    c = (rp.get("county") or "").strip().lower()
    if c:
        return c
    jur = (lead.get("jurisdiction") or "").strip()
    m = re.match(r"KY-(.+)", jur, re.I)
    if m:
        return m.group(1).lower()
    return ""


def _parse_book_page(lead: dict, rp: dict) -> tuple[str, str]:
    book = str(rp.get("book") or "").strip()
    page = str(rp.get("page") or "").strip()
    if book and page:
        return book, page
    case_id = str(lead.get("case_id") or "").strip()
    if "/" in case_id:
        b, p = case_id.split("/", 1)
        return b.strip(), p.strip()
    return book, page


def _lead_is_usable(lead: dict, rp: dict, county: str) -> bool:
    if county and _parse_county(lead, rp) and _parse_county(lead, rp) != county:
        return False
    book, page = _parse_book_page(lead, rp)
    inst = str(rp.get("instrument_type") or "").strip()
    owner = lead.get("owner_name") or rp.get("owner_name") or rp.get("grantor") or ""
    addr = lead.get("property_address") or rp.get("property_address") or ""
    blob = f"{owner} {addr} {book} {page} {inst}"
    if is_junk_portal_row(blob, rp):
        return False
    if inst and _LOGIN_JUNK.search(inst):
        return False
    if inst and not (book and page) and not addr and not owner:
        return False
    return bool(owner or addr or (book and page) or rp.get("legal_description"))


def _row_from_lead(lead: dict) -> dict | None:
    rp = lead.get("raw_payload") or {}
    if isinstance(rp, str):
        try:
            rp = json.loads(rp)
        except json.JSONDecodeError:
            rp = {}
    county = _parse_county(lead, rp)
    if not county:
        return None
    book, page = _parse_book_page(lead, rp)
    grantor = rp.get("grantor") or ""
    grantee = rp.get("grantee") or ""
    owner = lead.get("owner_name") or rp.get("owner_name") or grantor or ""
    merged = {
        **rp,
        "county": county,
        "book": book,
        "page": page,
        "grantor": grantor,
        "grantee": grantee,
        "owner_name": owner,
        "property_address": lead.get("property_address") or rp.get("property_address"),
        "instrument_type": rp.get("instrument_type") or "",
        "search_profile": rp.get("search_profile") or "",
        "amount_due": rp.get("amount_due") or rp.get("tax_due") or rp.get("total_due"),
        "legal_description": rp.get("legal_description") or "",
        "filter_reasons": rp.get("filter_reasons") or [],
    }
    scores = score_from_lead_data(merged)
    merged["investment_scores"] = scores
    merged["best_strategy"] = best_strategy(scores)
    reasons = list(merged["filter_reasons"])
    tier_row = {**merged, "amount_due": float(merged["amount_due"] or 0)}
    merged["hot_tier"] = hot_tier(tier_row, reasons)
    return {
        "hot_tier": merged.get("hot_tier", "C"),
        "search_profile": merged.get("search_profile"),
        "county": county,
        "instrument_type": merged.get("instrument_type"),
        "owner_name": owner or grantor,
        "grantee": grantee,
        "property_address": merged.get("property_address"),
        "legal_description": (merged.get("legal_description") or "")[:400],
        "amount_due": merged.get("amount_due"),
        "book": book,
        "page": page,
        "filter_reasons": reasons,
        "best_strategy": merged.get("best_strategy"),
        "pre_mls_score": scores.get("pre_mls_score"),
        "short_sale_score": scores.get("short_sale_score"),
        "document_downloaded": bool(rp.get("document_downloaded")),
        "storage_path": rp.get("storage_path") or "",
        "creative_scenarios": scores.get("creative_scenarios") or [],
        "primary_creative_play": scores.get("primary_creative_play"),
        "profile_reference": PROFILE_REFERENCE_META.get(
            merged.get("search_profile") or "", {}
        ),
    }


def fetch_leads(county: str) -> list[dict]:
    client = _get_client()
    if not client:
        raise SystemExit("Supabase client unavailable — check Doppler secrets")
    jurisdiction = f"KY-{county.strip().title()}"
    rows: list[dict] = []
    offset = 0
    page_size = 500
    while True:
        resp = (
            client.table("ft_leads")
            .select("id,owner_name,property_address,jurisdiction,case_id,raw_payload,source_key")
            .in_("source_key", list(SOURCE_KEYS))
            .eq("jurisdiction", jurisdiction)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def rebuild(county: str, *, dry_run: bool = False) -> Path:
    county = county.strip().lower()
    leads = fetch_leads(county)
    items: list[dict] = []
    skipped = 0
    for lead in leads:
        rp = lead.get("raw_payload") or {}
        if isinstance(rp, str):
            try:
                rp = json.loads(rp)
            except json.JSONDecodeError:
                rp = {}
        if not _lead_is_usable(lead, rp, county):
            skipped += 1
            continue
        row = _row_from_lead(lead)
        if row:
            items.append(row)
    items.sort(
        key=lambda x: (
            {"A": 0, "B": 1, "C": 2}.get(x.get("hot_tier", "C"), 3),
            -(x.get("pre_mls_score") or 0),
            -(float(x.get("amount_due") or 0)),
        ),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    EXPORTS.mkdir(parents=True, exist_ok=True)
    path = EXPORTS / f"{county}-filtered-{stamp}.json"
    payload = {"count": len(items), "leads": items}
    if dry_run:
        print(f"DRY-RUN would write {path} — {len(items)} leads ({skipped} skipped of {len(leads)} fetched)")
        return path
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {path} — {len(items)} leads ({skipped} skipped of {len(leads)} fetched)")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--county", default="scott", help="County slug, e.g. scott")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    rebuild(args.county, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
