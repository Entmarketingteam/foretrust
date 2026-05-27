#!/usr/bin/env python3
"""Link ft_clerk_documents.lead_id to ft_leads by county + book + page.

  doppler run --project foretrust-scraper --config dev -- python3 scripts/backfill_clerk_lead_ids.py
  doppler run --project foretrust-scraper --config dev -- python3 scripts/backfill_clerk_lead_ids.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import base64
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REF = "aqalynmkpktxevfmubnl"
SOURCE = "ecclix_batch"


def _token() -> str:
    t = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if t:
        return t.strip()
    raw = subprocess.check_output(
        ["security", "find-generic-password", "-s", "Supabase CLI", "-w"], text=True
    ).strip()
    if raw.startswith("go-keyring-base64:"):
        raw = base64.b64decode(raw[len("go-keyring-base64:"):]).decode()
    return raw.strip()


def q(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "User-Agent": "foretrust-clerk-link/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _county_key(jurisdiction: str | None, county: str | None) -> str:
    if jurisdiction and jurisdiction.startswith("KY-"):
        return jurisdiction[3:].lower()
    return (county or "").strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    leads = q(
        f"select id, jurisdiction, case_id, raw_payload from ft_leads "
        f"where source_key='{SOURCE}'"
    )
    index: dict[tuple[str, str, str], str] = {}
    for lead in leads:
        rp = lead.get("raw_payload") or {}
        book = str(rp.get("book") or "").strip()
        page = str(rp.get("page") or "").strip()
        if not book or not page:
            case = (lead.get("case_id") or "").strip()
            if "/" in case:
                book, page = case.split("/", 1)
        county = _county_key(lead.get("jurisdiction"), rp.get("county"))
        if county and book and page:
            index[(county, book.upper(), page)] = lead["id"]

    docs = q(
        f"select id, county, book, page, lead_id from ft_clerk_documents "
        f"where source_key='{SOURCE}'"
    )
    to_link: list[dict] = []
    already = 0
    unmatched = 0
    for doc in docs:
        if doc.get("lead_id"):
            already += 1
            continue
        ck = _county_key(None, doc.get("county"))
        book = str(doc.get("book") or "").strip().upper()
        page = str(doc.get("page") or "").strip()
        lead_id = index.get((ck, book, page))
        if lead_id:
            to_link.append({"doc_id": doc["id"], "lead_id": lead_id})
        else:
            unmatched += 1

    print("=== clerk → lead link ===")
    print(f"  leads indexed: {len(index)}")
    print(f"  clerk docs: {len(docs)}")
    print(f"  already linked: {already}")
    print(f"  will link: {len(to_link)}")
    print(f"  unmatched: {unmatched}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to UPDATE ft_clerk_documents.")
        return

    for i in range(0, len(to_link), 100):
        chunk = to_link[i : i + 100]
        pairs = ",".join(
            f"('{x['doc_id']}'::uuid, '{x['lead_id']}'::uuid)" for x in chunk
        )
        q(
            f"update ft_clerk_documents d set lead_id = v.lead_id "
            f"from (values {pairs}) as v(doc_id, lead_id) "
            f"where d.id = v.doc_id;"
        )
    print(f"[APPLY] linked {len(to_link)} clerk documents")


if __name__ == "__main__":
    main()
