#!/usr/bin/env python3
"""Merge all runs into a master scenario reference library (examples + PDF index).

Reads: portal-intel JSON, scenario-library folders, ecclix-sprint CSV, Supabase ft_leads.
Writes: scraper-service/exports/scenario-library/MASTER-INDEX.md + per-scenario merges.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scraper-service"
sys.path.insert(0, str(ROOT))

from app.pipeline.creative_finance_signals import detect_scenarios, scenario_outreach_hint
from app.pipeline.investment_scorer import score_from_lead_data

EXPORTS = ROOT / "exports"
LIB_ROOT = EXPORTS / "scenario-library"
PORTAL = EXPORTS / "portal-intel"
SPRINT = EXPORTS / "ecclix-sprint"
ACTIONABLE = EXPORTS / "actionable-leads"
PDF_ROOT = EXPORTS / "ecclix"


def _load_json_manifests() -> list[dict]:
    leads: list[dict] = []
    if not PORTAL.exists():
        return leads
    for path in sorted(PORTAL.glob("*-filtered-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for item in data.get("leads") or []:
            item["_source_file"] = str(path.name)
            leads.append(item)
    return leads


def _load_scenario_library_runs() -> list[dict]:
    leads: list[dict] = []
    if not LIB_ROOT.exists():
        return leads
    for examples in LIB_ROOT.glob("*/examples.json"):
        try:
            data = json.loads(examples.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for item in data.get("leads") or []:
            item["_source_file"] = str(examples.parent)
            leads.append(item)
    return leads


def _load_actionable_csv() -> list[dict]:
    leads: list[dict] = []
    for path in sorted(ACTIONABLE.glob("properties-*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["search_module"] = "delinquent_tax"
                row["_source_file"] = path.name
                leads.append(row)
    return leads


def _normalize(lead: dict) -> dict:
    payload = {
        "owner_name": lead.get("owner_name") or lead.get("grantor"),
        "grantor": lead.get("grantor"),
        "grantee": lead.get("grantee"),
        "property_address": lead.get("property_address"),
        "legal_description": lead.get("legal_description") or "",
        "instrument_type": lead.get("instrument_type"),
        "amount_due": lead.get("amount_due"),
        "search_profile": lead.get("search_profile"),
        "lp_active": lead.get("lp_active") or (lead.get("instrument_type") == "LP"),
        "row_text": lead.get("row_text") or "",
        "storage_path": lead.get("storage_path"),
        "document_downloaded": lead.get("document_downloaded"),
        "county": lead.get("county"),
        "book": lead.get("book"),
        "page": lead.get("page"),
        "filter_reasons": lead.get("filter_reasons"),
        "_source_file": lead.get("_source_file"),
    }
    scores = score_from_lead_data(payload)
    payload["investment_scores"] = scores
    payload["creative_scenarios"] = scores.get("creative_scenarios") or detect_scenarios(payload)
    payload["primary_creative_play"] = scores.get("primary_creative_play")
    return payload


def _dedupe_key(lead: dict) -> str:
    return "|".join(
        [
            str(lead.get("county") or ""),
            str(lead.get("book") or lead.get("bill_number") or ""),
            str(lead.get("page") or ""),
            str(lead.get("owner_name") or lead.get("grantor") or ""),
            str(lead.get("property_address") or ""),
            str(lead.get("search_profile") or lead.get("_source_file") or ""),
        ]
    )


def merge_master(*, max_per_scenario: int = 50) -> Path:
    raw: list[dict] = []
    raw.extend(_load_json_manifests())
    raw.extend(_load_scenario_library_runs())
    raw.extend(_load_actionable_csv())

    try:
        from app.pipeline.deal_package import fetch_distress_leads

        for row in __import__("asyncio").run(fetch_distress_leads(limit=2000)):
            raw.append(row)
    except Exception:
        pass

    seen: set[str] = set()
    normalized: list[dict] = []
    for item in raw:
        n = _normalize(item)
        key = _dedupe_key(n)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(n)

    by_scenario: dict[str, list[dict]] = {}
    for lead in normalized:
        for sc in lead.get("creative_scenarios") or ["unclassified_distress"]:
            by_scenario.setdefault(sc, []).append(lead)

    master = LIB_ROOT / "MASTER"
    master.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Master scenario reference library",
        "",
        f"**Total unique leads:** {len(normalized)}",
        f"**Scenarios with examples:** {len(by_scenario)}",
        "",
        "| Scenario | Count | Top play |",
        "|----------|-------|----------|",
    ]

    for scenario, items in sorted(by_scenario.items(), key=lambda x: -len(x[1])):
        scen_dir = master / scenario
        scen_dir.mkdir(parents=True, exist_ok=True)
        items.sort(
            key=lambda x: (
                0 if x.get("document_downloaded") else 1,
                -((x.get("investment_scores") or {}).get("subto") or 0),
            )
        )
        top = items[:max_per_scenario]
        hint = scenario_outreach_hint(scenario)
        (scen_dir / "README.md").write_text(
            f"# {scenario}\n\n{hint}\n\n**Examples:** {len(top)} (of {len(items)} total)\n",
            encoding="utf-8",
        )
        (scen_dir / "examples.json").write_text(
            json.dumps({"scenario": scenario, "count": len(top), "leads": top}, indent=2, default=str),
            encoding="utf-8",
        )
        csv_path = scen_dir / "examples.csv"
        if top:
            keys = list(top[0].keys())
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                for row in top:
                    w.writerow(row)
        lines.append(f"| [{scenario}]({scenario}/README.md) | {len(items)} | {hint[:60]}... |")

    (master / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {master / 'INDEX.md'} — {len(normalized)} leads, {len(by_scenario)} scenarios")
    return master


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-per-scenario", type=int, default=50)
    args = parser.parse_args()
    merge_master(max_per_scenario=args.max_per_scenario)


if __name__ == "__main__":
    main()
