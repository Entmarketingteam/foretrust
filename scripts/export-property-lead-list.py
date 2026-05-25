#!/usr/bin/env python3
"""Export actionable property list: address, owner, distress reason, next step.

Uses Supabase ft_leads (real data). Ignores junk ecclix-sprint CSVs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scraper-service"
sys.path.insert(0, str(ROOT))

from app.pipeline.distress_reason import distress_reason, next_action


def fetch_leads(
    source_key: str | None,
    jurisdiction: str | None,
    limit: int,
    *,
    all_sources: bool = False,
) -> list[dict]:
    from app.storage.supabase_client import _get_client

    client = _get_client()
    if not client:
        print("Supabase not configured", file=sys.stderr)
        return []

    sources = (
        ["ecclix_csv_import", "ecclix_batch"]
        if all_sources
        else ([source_key] if source_key else [])
    )
    rows: list[dict] = []
    for sk in sources or [None]:
        q = client.table("ft_leads").select("*")
        if sk:
            q = q.eq("source_key", sk)
        if jurisdiction:
            q = q.ilike("jurisdiction", f"%{jurisdiction}%")
        q = q.order("hot_score", desc=True).limit(limit)
        rows.extend(q.execute().data or [])
    # Dedupe by owner+address
    seen: set[str] = set()
    out: list[dict] = []
    for lead in sorted(rows, key=lambda x: -(x.get("hot_score") or 0)):
        key = f"{lead.get('owner_name')}|{lead.get('property_address')}|{lead.get('parcel_number')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(lead)
    return out[:limit]


def is_real_property_row(lead: dict) -> bool:
    addr = (lead.get("property_address") or "").strip()
    owner = (lead.get("owner_name") or "").strip()
    blob = (addr + owner).lower()
    if "log in" in blob or "ecclix" in blob and "password" in blob:
        return False
    if addr and any(c.isdigit() for c in addr[:12]):
        return True
    payload = lead.get("raw_payload") or {}
    if isinstance(payload, dict) and payload.get("map_id"):
        return True
    return bool(owner) and len(owner) < 120 and "," in owner


def row_out(lead: dict) -> dict:
    payload = lead.get("raw_payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return {
        "county": (lead.get("jurisdiction") or "").replace("KY-", ""),
        "owner_name": lead.get("owner_name"),
        "property_address": lead.get("property_address"),
        "mailing_address": lead.get("mailing_address"),
        "parcel_map_id": lead.get("parcel_number") or payload.get("map_id"),
        "lead_type": lead.get("lead_type"),
        "distress_reason": payload.get("distress_reason") or distress_reason(lead),
        "amount_due_or_value": lead.get("estimated_value") or payload.get("amount_due"),
        "tax_year": payload.get("tax_year"),
        "bill_number": payload.get("bill_number") or lead.get("case_id"),
        "hot_score": lead.get("hot_score"),
        "best_strategy": (payload.get("best_strategy") or ""),
        "next_action": payload.get("next_action") or next_action(lead),
        "detail_url": payload.get("detail_url", ""),
        "source": lead.get("source_key"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="ecclix_csv_import")
    p.add_argument(
        "--all-sources",
        action="store_true",
        help="Merge ecclix_csv_import + ecclix_batch from Supabase",
    )
    p.add_argument("--jurisdiction", default="Scott")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--human-only", action="store_true", help="Skip LLC/bank names")
    p.add_argument("--min-due", type=float, default=500)
    args = p.parse_args()

    leads = fetch_leads(
        args.source,
        args.jurisdiction,
        args.limit,
        all_sources=args.all_sources,
    )
    rows = []
    for lead in leads:
        if not is_real_property_row(lead):
            continue
        out = row_out(lead)
        due = float(out.get("amount_due_or_value") or 0)
        if args.min_due and due < args.min_due:
            continue
        if args.human_only:
            from app.pipeline.investment_scorer import is_human_owner
            if not is_human_owner(out.get("owner_name")):
                continue
        rows.append(out)

    out_dir = ROOT / "exports" / "actionable-leads"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tag = (args.jurisdiction or "all").lower().replace(" ", "-")
    csv_path = out_dir / f"properties-{tag}-{stamp}.csv"
    md_path = out_dir / f"properties-{tag}-{stamp}.md"

    fields = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    lines = [
        f"# Actionable properties — {args.jurisdiction or 'all'}",
        f"**{len(rows)}** rows with street address + distress reason",
        "",
        "| Owner | Address | Reason | Due | Next |",
        "|-------|---------|--------|-----|------|",
    ]
    for r in rows[:50]:
        lines.append(
            f"| {str(r.get('owner_name',''))[:35]} "
            f"| {str(r.get('property_address',''))[:30]} "
            f"| {str(r.get('distress_reason',''))[:40]} "
            f"| ${float(r.get('amount_due_or_value') or 0):,.0f} "
            f"| {r.get('next_action','')} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "exported": len(rows),
        "csv": str(csv_path),
        "md": str(md_path),
        "note": "Sprint CSVs in ecclix-sprint/ are NOT used — they contain login junk.",
    }, indent=2))


if __name__ == "__main__":
    main()
