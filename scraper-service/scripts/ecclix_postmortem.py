#!/usr/bin/env python3
"""Post–day-pass audit: CSVs, Supabase ft_leads, runs, clerk docs.

Run from scraper-service/:
  doppler run --project foretrust-scraper --config dev -- python3 scripts/ecclix_postmortem.py
  doppler run --project foretrust-scraper --config dev -- python3 scripts/ecclix_postmortem.py --write-md
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPORTS = ROOT / "exports"
SPRINT = EXPORTS / "ecclix-sprint"
LOGIN_JUNK = re.compile(
    r"eCCLIX|Login|Subscribe|Privacy Policy|Getting Started|Public Sign-Up",
    re.I,
)


def _classify_csv(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}
    lines = text.count("\n")
    junk = bool(LOGIN_JUNK.search(text))
    # Heuristic: good instrument CSV has book/page columns with data
    good_rows = 0
    if not junk and path.suffix == ".csv":
        try:
            with path.open(newline="", encoding="utf-8", errors="replace") as fh:
                reader = csv.DictReader(fh)
                for i, row in enumerate(reader):
                    if i >= 50:
                        break
                    bk = (row.get("book") or row.get("Book") or "").strip()
                    if bk and bk.upper() not in ("BOOK", "NAVIGATION"):
                        good_rows += 1
        except Exception:
            pass
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "lines": lines,
        "login_junk": junk,
        "sample_good_rows": good_rows,
    }


def _audit_csv_dirs() -> dict:
    out: dict = {"sprint_files": [], "batch_exports": []}
    if SPRINT.is_dir():
        for p in sorted(SPRINT.glob("*.csv")):
            out["sprint_files"].append(_classify_csv(p))
    for p in sorted(EXPORTS.glob("ecclix_batch_*.csv")):
        out["batch_exports"].append(_classify_csv(p))
    junk = sum(1 for x in out["sprint_files"] if x.get("login_junk"))
    good = sum(1 for x in out["sprint_files"] if not x.get("login_junk") and x.get("sample_good_rows", 0) > 0)
    out["sprint_summary"] = {
        "total_csv": len(out["sprint_files"]),
        "login_junk": junk,
        "likely_good": good,
        "empty_or_unknown": len(out["sprint_files"]) - junk - good,
    }
    return out


def _audit_supabase() -> dict:
    import os

    from supabase import create_client

    from app.pipeline.property_address import is_valid_street_address, normalize_property_address

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return {"error": "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set"}

    c = create_client(url, key)
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (
            c.table("ft_leads")
            .select("id,source_key,lead_type,jurisdiction,property_address,owner_name,case_id,raw_payload")
            .eq("source_key", "ecclix_batch")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        if not batch:
            break
        rows.extend(batch)
        offset += 1000

    buckets = Counter()
    valid_street = 0
    could_extract = 0
    for r in rows:
        rp = r.get("raw_payload") or {}
        if rp.get("search_module") == "delinquent_tax" or rp.get("bill_number"):
            buckets["tax_delinquent"] += 1
        elif rp.get("recovered_from_cells"):
            buckets["instrument_recovered"] += 1
        elif rp.get("cells"):
            buckets["tax_cells_unparsed"] += 1
        else:
            buckets["instrument_other"] += 1

        addr = r.get("property_address") or ""
        legal = rp.get("legal_description") or addr
        if is_valid_street_address(addr):
            valid_street += 1
        elif normalize_property_address(None, legal=str(legal)):
            could_extract += 1

    docs = (
        c.table("ft_clerk_documents")
        .select("id,lead_id,storage_path,county,book,page", count="exact")
        .eq("source_key", "ecclix_batch")
        .limit(1)
        .execute()
    )
    doc_rows = (
        c.table("ft_clerk_documents")
        .select("lead_id,storage_path")
        .eq("source_key", "ecclix_batch")
        .limit(5000)
        .execute()
        .data
    )
    pending_pdf = sum(1 for d in doc_rows if "pending/" in (d.get("storage_path") or ""))
    linked = sum(1 for d in doc_rows if d.get("lead_id"))

    runs = (
        c.table("ft_lead_source_runs")
        .select("records_found,records_new,status,started_at,error_message")
        .eq("source_key", "ecclix_batch")
        .order("started_at", desc=True)
        .limit(40)
        .execute()
        .data
    )
    run_found = [r.get("records_found") or 0 for r in runs]
    zero_runs = sum(1 for x in run_found if x == 0)
    nonzero = [x for x in run_found if x > 0]

    return {
        "ft_leads_ecclix_batch": len(rows),
        "buckets": dict(buckets),
        "valid_street_address": valid_street,
        "could_normalize_street_from_legal": could_extract,
        "ft_clerk_documents": docs.count,
        "clerk_pending_storage": pending_pdf,
        "clerk_linked_lead_id": linked,
        "recent_runs": len(runs),
        "runs_with_zero_found": zero_runs,
        "runs_with_data": len(nonzero),
        "max_records_found_recent": max(nonzero) if nonzero else 0,
        "by_jurisdiction": dict(Counter(r.get("jurisdiction") for r in rows).most_common(8)),
        "by_lead_type": dict(Counter(r.get("lead_type") for r in rows).most_common(8)),
    }


def _recommendations(csv_audit: dict, db_audit: dict) -> list[str]:
    rec: list[str] = []
    sprint = csv_audit.get("sprint_summary", {})
    if sprint.get("login_junk", 0) > 5:
        rec.append(
            f"Ignore {sprint['login_junk']} ecclix-sprint CSVs with login-page junk; "
            "do not re-import. Use ecclix_csv_import / actionable exports for tax."
        )
    if db_audit.get("clerk_linked_lead_id", 0) == 0 and db_audit.get("ft_clerk_documents", 0) > 0:
        rec.append("Run scripts/backfill_clerk_lead_ids.py to marry clerk PDF metadata to ft_leads.")
    if db_audit.get("could_normalize_street_from_legal", 0) > 50:
        rec.append("Run scripts/backfill_ecclix_addresses.py to pull situs addresses out of legal text.")
    if db_audit.get("clerk_pending_storage", 0) > 100:
        rec.append(
            "Most clerk rows use pending/ storage — PDFs were not downloaded on Railway. "
            "Next pass: download_documents=true on Alienware with ECCLIX_EXPORT_DIR set."
        )
    if db_audit.get("runs_with_zero_found", 0) > 10:
        rec.append(
            "Recent ecclix_batch runs mostly returned 0 — day pass expired or wrong counties in Doppler. "
            "Do not schedule more scrapes until pass is renewed."
        )
    rec.append(
        "Do NOT run backfill_ecclix.py --apply without the recovered-instrument guard — "
        "it would delete ~1k valid instrument rows."
    )
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-md", action="store_true", help="Write exports/ecclix-postmortem.md")
    args = ap.parse_args()

    csv_audit = _audit_csv_dirs()
    db_audit = _audit_supabase()
    recs = _recommendations(csv_audit, db_audit)

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "csv": csv_audit,
        "database": db_audit,
        "recommendations": recs,
    }

    print(json.dumps(report, indent=2))
    print("\n=== Recommendations ===")
    for i, r in enumerate(recs, 1):
        print(f"{i}. {r}")

    if args.write_md:
        md_path = EXPORTS / "ecclix-postmortem.md"
        lines = [
            "# eCCLIX post-mortem",
            f"\nGenerated: {report['generated_utc']}\n",
            "## Sprint CSVs",
            f"- Total: {csv_audit.get('sprint_summary', {}).get('total_csv')}",
            f"- Login junk: {csv_audit.get('sprint_summary', {}).get('login_junk')}",
            f"- Likely good: {csv_audit.get('sprint_summary', {}).get('likely_good')}",
            "\n## Supabase (ecclix_batch)",
        ]
        for k, v in db_audit.items():
            if k != "error":
                lines.append(f"- **{k}**: {v}")
        lines.append("\n## Next steps\n")
        for r in recs:
            lines.append(f"- {r}")
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {md_path}")


if __name__ == "__main__":
    main()
