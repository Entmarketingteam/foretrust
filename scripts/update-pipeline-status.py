#!/usr/bin/env python3
"""Write scraper-service/exports/pipeline-status.json for Cursor rules + operators."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "scraper-service" / "exports"
ECCLIX_LOCK = Path("/tmp/foretrust-ecclix.lock")
SCENARIO_LOG = Path("/tmp/foretrust-scenario-library.log")
ENRICH_LOG = Path("/tmp/foretrust-parallel-enrichment.log")

COUNTIES = ("scott", "bourbon", "woodford", "franklin")


def _latest(glob: str) -> Path | None:
    matches = sorted(EXPORTS.glob(glob), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _count_actionable_rows(md_path: Path) -> int:
    text = md_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\*\*(\d+)\*\*\s+rows", text)
    if m:
        return int(m.group(1))
    return max(0, text.count("\n| ") - 1)


def _load_portal_intel(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"count": 0, "file": str(path.name)}
    return {
        "count": data.get("count") or len(data.get("leads") or []),
        "file": path.name,
    }


def _master_stats() -> dict:
    index = EXPORTS / "scenario-library" / "MASTER" / "INDEX.md"
    if not index.exists():
        return {}
    text = index.read_text(encoding="utf-8", errors="replace")
    out: dict = {"index_file": str(index.relative_to(ROOT))}
    m = re.search(r"\*\*Total unique leads:\*\*\s*(\d+)", text)
    if m:
        out["total_unique_leads"] = int(m.group(1))
    m = re.search(r"\*\*Scenarios with examples:\*\*\s*(\d+)", text)
    if m:
        out["scenario_count"] = int(m.group(1))
    return out


def _log_hint(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    try:
        tail = path.read_text(encoding="utf-8", errors="replace")[-8000:]
    except OSError:
        return {"exists": True}
    county = None
    for c in COUNTIES:
        if re.search(rf"SCENARIO LIBRARY:\s*{c}\b|sprint {c}/", tail, re.I):
            county = c
    mode = None
    for pat in ("scenario_library", "pre_mls_sprint", "actionable export", "COMPLETE"):
        if pat.lower() in tail.lower():
            mode = pat
    return {
        "exists": True,
        "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "likely_county": county,
        "likely_phase": mode,
        "last_line": tail.strip().splitlines()[-1][:200] if tail.strip() else "",
    }


def build_status() -> dict:
    actionable: dict[str, dict] = {}
    for county in COUNTIES:
        md = _latest(f"actionable-leads/properties-{county}-*.md")
        if md:
            actionable[county] = {
                "file": str(md.relative_to(ROOT)),
                "rows": _count_actionable_rows(md),
                "updated_utc": datetime.fromtimestamp(md.stat().st_mtime, tz=timezone.utc).isoformat(),
            }

    portal: dict[str, dict] = {}
    for county in COUNTIES:
        j = _latest(f"portal-intel/{county}-filtered-*.json")
        if j:
            portal[county] = _load_portal_intel(j)
            portal[county]["file"] = str(j.relative_to(ROOT))

    scenario_dirs = [
        p.name
        for p in sorted((EXPORTS / "scenario-library").glob("*-*"))
        if p.is_dir() and p.name != "MASTER"
    ]

    return {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "ecclix_lock_held": ECCLIX_LOCK.is_dir(),
        "counties": list(COUNTIES),
        "actionable_tax": actionable,
        "portal_intel": portal,
        "scenario_library_dirs": scenario_dirs,
        "master": _master_stats(),
        "known_issues": [
            "ft_clerk_documents: apply supabase/migrations/20260525100000_ft_clerk_documents.sql (or supabase db push) until PDF upserts succeed",
            "One eCCLIX login — never run parallel browser sessions on same account",
            "KCOJ CourtNet selectors may need update (search form not found)",
        ],
        "active_jobs": {
            "scenario_library_log": _log_hint(SCENARIO_LOG),
            "parallel_enrichment_log": _log_hint(ENRICH_LOG),
        },
        "key_scripts": {
            "ecclix_24h": "scripts/run-scenario-library-24h.sh",
            "party_intel": "scripts/run-party-intel-24h.sh",
            "parallel_enrichment": "scripts/run-parallel-enrichment.sh",
            "best_deals": "scripts/build-best-deals.py",
            "actionable_export": "scripts/export-property-lead-list.py",
            "scenario_merge": "scripts/export-scenario-reference-library.py",
        },
        "data_roots": {
            "actionable": "scraper-service/exports/actionable-leads/",
            "portal_intel": "scraper-service/exports/portal-intel/",
            "scenario_library": "scraper-service/exports/scenario-library/",
            "pdfs": "scraper-service/exports/ecclix/",
            "best_deals": "scraper-service/exports/best-deals/",
        },
    }


def main() -> None:
    out_path = EXPORTS / "pipeline-status.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    status = build_status()
    out_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} ({status.get('master', {}).get('total_unique_leads', '?')} master leads)")


if __name__ == "__main__":
    main()
