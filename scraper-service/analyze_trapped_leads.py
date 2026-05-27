#!/usr/bin/env python3
"""Read-only: quantify instrument records recoverable from ecclix_batch blobs.

Pulls every ft_leads.raw_payload->'cells' for source_key='ecclix_batch',
runs the exploder, and reports how many real instrument records are hiding in
the data vs how many proper leads exist today.
"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter

from app.connectors.residential.ecclix_row_parser import explode_instrument_cells

REF = "aqalynmkpktxevfmubnl"


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
            "User-Agent": "foretrust-analyze/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def main():
    needle = " ".join(sys.argv[1:]).upper().strip()
    rows = q(
        "select id, raw_payload->'cells' as cells, "
        "jsonb_array_length(raw_payload->'cells') as ncells "
        "from ft_leads where source_key='ecclix_batch' and raw_payload ? 'cells'"
    )
    print(f"ecclix_batch leads with a cells array: {len(rows)}")

    total_recs = 0
    by_county_lead = Counter()  # records recovered per source lead bucket
    by_type = Counter()
    blob_leads = 0           # leads whose cells explode into >1 record
    multi_records = 0        # records that live inside a blob lead
    needle_hits = []
    sample = []

    for row in rows:
        cells = row.get("cells") or []
        recs = explode_instrument_cells(cells)
        total_recs += len(recs)
        if len(recs) > 1:
            blob_leads += 1
            multi_records += len(recs)
        for r in recs:
            by_type[r["instrument_type"]] += 1
            if len(sample) < 5 and len(recs) > 1:
                sample.append(r)
            if needle:
                hay = f"{r['grantor']} {r['grantee']} {r['legal_description']}".upper()
                if needle in hay:
                    needle_hits.append(r)

    print(f"\nTotal instrument records recoverable: {total_recs}")
    print(f"Leads that are actually blobs (>1 record): {blob_leads}")
    print(f"Records trapped inside those blobs: {multi_records}")
    print(f"\nRecords by instrument type:")
    for t, c in by_type.most_common(25):
        print(f"  {t or '(none)':10} {c}")

    print(f"\nSample recovered-from-blob records:")
    for r in sample:
        print(f"  {r['instrument_type']:6} bk={r['book']} pg={r['page']} "
              f"grantor={r['grantor']!r} grantee={r['grantee']!r} "
              f"date={r['recorded_date']} desc={r['legal_description']!r}")

    if needle:
        print(f"\n=== matches for {needle!r}: {len(needle_hits)} ===")
        for r in needle_hits[:20]:
            print(f"  {r['instrument_type']:6} bk={r['book']} pg={r['page']} "
                  f"grantor={r['grantor']!r} grantee={r['grantee']!r} "
                  f"date={r['recorded_date']} desc={r['legal_description']!r}")


if __name__ == "__main__":
    main()
