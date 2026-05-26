"""Parse eCCLIX table-scraper delinquent tax CSV exports → Foretrust leads."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from app.models import Lead, LeadType, RawRecord, Vertical
from app.pipeline.distress_scorer import compute_hot_score
from app.pipeline.investment_scorer import best_strategy, score_from_lead_data

SOURCE_KEY = "ecclix_csv_import"
DEFAULT_COUNTY = "scott"


def parse_amount(status_cell: str) -> tuple[float | None, str]:
    s = (status_cell or "").strip().strip('"').replace("%20", " ")
    if not s:
        return None, s
    low = s.lower()
    if "paid" in low or "collection" in low:
        return None, s
    m = re.search(r"([\d,]+\.?\d*)", s)
    if not m:
        return None, s
    try:
        return float(m.group(1).replace(",", "")), s
    except ValueError:
        return None, s


def has_street_number(address: str) -> bool:
    return bool(re.match(r"^\d+\s", (address or "").strip()))


def parse_ecclix_delinquent_csv(path: str | Path) -> list[dict[str, Any]]:
    """Parse one table-scraper CSV file; returns raw row dicts (may duplicate bills)."""
    path = Path(path)
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 8:
                continue
            bill = row[0].strip().strip('"')
            if not bill.isdigit():
                continue
            amt, status = parse_amount(row[7])
            rows.append({
                "bill_number": bill,
                "tax_year": row[2].strip().strip('"'),
                "owner_name": row[3].strip().strip('"'),
                "property_address": row[4].strip().strip('"'),
                "map_id": row[5].strip().strip('"'),
                "amount_due": amt,
                "status": status,
                "detail_url": row[1].strip().strip('"') if row[1].startswith("http") else "",
                "source_file": path.name,
            })
    return rows


def merge_ecclix_csv_files(paths: list[str | Path]) -> list[dict[str, Any]]:
    """Merge multiple exports; dedupe by bill_number (last file wins)."""
    by_bill: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in parse_ecclix_delinquent_csv(path):
            bill = row["bill_number"]
            if bill in by_bill:
                row["source_files"] = by_bill[bill].get("source_files", []) + [row["source_file"]]
            else:
                row["source_files"] = [row["source_file"]]
            by_bill[bill] = row
    return list(by_bill.values())


def filter_tiers(
    rows: list[dict[str, Any]],
    *,
    min_amount: float = 500.0,
    require_street_number: bool = True,
    active_only: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Bucket rows per KY-DISTRESSED-LEAD-MAP tiers."""
    active = [r for r in rows if r.get("amount_due") is not None] if active_only else rows
    tier_a = [
        r for r in active
        if (r.get("amount_due") or 0) >= min_amount
        and (has_street_number(r.get("property_address", "")) if require_street_number else True)
    ]
    tier_b = [
        r for r in active
        if (r.get("amount_due") or 0) >= min_amount
        and not has_street_number(r.get("property_address", ""))
    ]
    tier_c = [
        r for r in active
        if 100 <= (r.get("amount_due") or 0) < min_amount
        and has_street_number(r.get("property_address", ""))
    ]
    small = [r for r in active if (r.get("amount_due") or 0) < 100]
    paid = [r for r in rows if r.get("amount_due") is None]
    return {
        "all": rows,
        "active": active,
        "tier_a": tier_a,
        "tier_b": tier_b,
        "tier_c": tier_c,
        "small": small,
        "paid_or_closed": paid,
    }


def enrich_rows(rows: list[dict[str, Any]], county: str = DEFAULT_COUNTY) -> list[dict[str, Any]]:
    for r in rows:
        r["county"] = county
        r["investment_scores"] = score_from_lead_data({
            "owner_name": r.get("owner_name"),
            "property_address": r.get("property_address"),
            "amount_due": r.get("amount_due"),
            "parcel_number": r.get("map_id"),
            "search_module": "delinquent_tax",
        })
        r["best_strategy"] = best_strategy(r["investment_scores"])
        r["tier"] = (
            "A" if (r.get("amount_due") or 0) >= 500 and has_street_number(r.get("property_address", ""))
            else "B" if (r.get("amount_due") or 0) >= 500
            else "C" if (r.get("amount_due") or 0) >= 100
            else "D"
        )
    return rows


def rows_to_leads(rows: list[dict[str, Any]], county: str = DEFAULT_COUNTY) -> list[Lead]:
    leads: list[Lead] = []
    for r in enrich_rows(rows, county=county):
        if r.get("amount_due") is None:
            continue
        data = {
            **r,
            "county": county,
            "search_module": "delinquent_tax",
            "imported_from": "ecclix_csv",
        }
        lead = Lead(
            source_key=SOURCE_KEY,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction=f"KY-{county.title()}",
            lead_type=LeadType.TAX_LIEN,
            owner_name=r.get("owner_name"),
            property_address=r.get("property_address"),
            parcel_number=r.get("map_id"),
            case_id=r.get("bill_number"),
            estimated_value=r.get("amount_due"),
            city="Georgetown",
            state="KY",
            raw_payload=data,
        )
        lead.hot_score = compute_hot_score(lead)
        if (r.get("amount_due") or 0) >= 2000:
            lead.hot_score = min(100, (lead.hot_score or 0) + 15)
        leads.append(lead)
    return leads


def import_paths(
    paths: list[str | Path],
    *,
    county: str = DEFAULT_COUNTY,
    tier: str = "A",
    min_amount: float = 500.0,
) -> tuple[list[Lead], dict[str, Any]]:
    """Full pipeline: merge → filter → leads + summary stats."""
    merged = merge_ecclix_csv_files(paths)
    buckets = filter_tiers(merged, min_amount=min_amount)
    key = f"tier_{tier.lower()}" if tier.lower() in ("a", "b", "c") else "active"
    selected = buckets.get(key, buckets["tier_a"])
    selected.sort(key=lambda x: (-(x.get("amount_due") or 0), x.get("owner_name", "")))
    leads = rows_to_leads(selected, county=county)
    summary = {
        "files": len(paths),
        "unique_bills": len(merged),
        "active_unpaid": len(buckets["active"]),
        "tier_a": len(buckets["tier_a"]),
        "tier_b": len(buckets["tier_b"]),
        "tier_c": len(buckets["tier_c"]),
        "imported_leads": len(leads),
        "county": county,
        "tier_filter": tier,
    }
    return leads, summary
