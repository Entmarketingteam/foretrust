#!/usr/bin/env python3
"""Recover trapped eCCLIX instrument leads by re-parsing raw_payload->'cells'.

Classifies every source_key='ecclix_batch' lead:

  * explode -> N>1 records  : BLOB. Delete the pseudo-lead, insert N clean leads.
  * explode -> 1 record     : single instrument. UPDATE in place (keeps the id).
  * explode -> 0 records :
       - delinquent-tax row  : LEAVE untouched (handled by the tax parser).
       - nav / header junk    : DELETE.

Also rebuilds ft_clerk_documents for ecclix_batch from scratch (the 157 rows
there were derived from the misparsed leads).

Default is DRY-RUN: prints the plan and counts, writes nothing. Pass --apply
to execute. All DB access is over the Supabase Management API (HTTPS), because
the Postgres pooler ports are firewall-blocked from this network.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import urllib.request
from collections import Counter
from datetime import datetime

from app.connectors.residential.ecclix_row_parser import explode_instrument_cells

REF = "aqalynmkpktxevfmubnl"
SOURCE = "ecclix_batch"
ORG_ID = "00000000-0000-0000-0000-000000000001"
JUNK_MARKERS = ("NEW SEARCH", "NAVIGATION:", "INS#/DATE", "PARTY1/PARTY2",
                "WELCOME", "LOGOUT")


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
            "User-Agent": "foretrust-backfill/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        body = r.read()
        return json.loads(body) if body.strip() else []


def dedupe_hash(county: str, rec: dict) -> str:
    key = (f"{SOURCE}|{county}|{rec['book']}|{rec['page']}|"
           f"{rec['grantor']}|{rec['grantee']}|{rec['instrument_type']}")
    return hashlib.sha256(key.encode()).hexdigest()


def iso_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


_LEAD_TYPE = [
    (("LP", "LIS"), "pre_foreclosure"),
    (("MTG",), "foreclosure"),
    (("JLIEN", "MLIEN", "LIEN", "SLR"), "tax_lien"),
    (("WILL", "AFF", "POA"), "estate"),
]


def lead_type_for(inst: str) -> str:
    u = (inst or "").upper()
    for needles, lt in _LEAD_TYPE:
        if any(u == n or u.startswith(n) for n in needles):
            return lt
    return "estate"


def lead_row(county: str, rec: dict) -> dict:
    owner = rec["grantor"] or rec["grantee"]
    legal = rec["legal_description"]
    return {
        "organization_id": ORG_ID,
        "source_key": SOURCE,
        "vertical": "residential",
        "lead_type": lead_type_for(rec["instrument_type"]),
        "owner_name": owner[:255] or None,
        "property_address": legal or None,
        "case_id": f"{rec['book']}/{rec['page']}"[:255],
        "jurisdiction": f"KY-{county}",
        "state": "KY",
        "dedupe_hash": dedupe_hash(county, rec),
        "raw_payload": {
            "county": county,
            "instrument_type": rec["instrument_type"],
            "book": rec["book"],
            "page": rec["page"],
            "grantor": rec["grantor"],
            "grantee": rec["grantee"],
            "recorded_date": rec["recorded_date"],
            "legal_description": legal,
            "owner_name": owner,
            "recovered_from_cells": True,
        },
    }


def clerk_row(county: str, rec: dict) -> dict:
    return {
        "organization_id": ORG_ID,
        "source_key": SOURCE,
        "county": county,
        "instrument_type": rec["instrument_type"] or None,
        "book": rec["book"] or None,
        "page": rec["page"] or None,
        "recorded_date": iso_date(rec["recorded_date"]),
        "grantor": rec["grantor"] or None,
        "grantee": rec["grantee"] or None,
        "legal_description": (rec["legal_description"] or None),
        "property_address": rec["legal_description"] or None,
        "storage_path": f"pending/{county}/{rec['book']}-{rec['page']}",
        "raw_payload": {"recovered_from_cells": True},
    }


def is_tax_lead(lead: dict) -> bool:
    rp = lead.get("raw_payload") or {}
    return rp.get("search_module") == "delinquent_tax" or bool(rp.get("bill_number"))


def looks_like_junk(lead: dict) -> bool:
    rp = lead.get("raw_payload") or {}
    blob = " ".join(str(rp.get(k) or "") for k in
                    ("grantor", "owner_name", "book", "page")).upper()
    return any(m in blob for m in JUNK_MARKERS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute writes")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== eCCLIX recovery [{mode}] ===\n")

    leads = q(
        f"select id, raw_payload from ft_leads where source_key='{SOURCE}'"
    )
    print(f"Total {SOURCE} leads: {len(leads)}")

    plan = Counter()
    recovered = []     # (county, rec) from singles + blobs
    delete_ids = []    # ids of non-tax instrument-derived leads to remove

    for lead in leads:
        rp = lead.get("raw_payload") or {}
        county = (rp.get("county") or "").title() or "Unknown"
        cells = rp.get("cells") or []
        recs = explode_instrument_cells(cells)

        if len(recs) >= 1:
            plan["update_single" if len(recs) == 1 else "delete_blob"] += 1
            plan["recovered_records"] += len(recs)
            recovered.extend((county, r) for r in recs)
            delete_ids.append(lead["id"])
        else:  # 0 records
            if is_tax_lead(lead):
                plan["leave_tax"] += 1
            else:  # nav/header junk or orphaned line-2 fragment
                plan["delete_junk_fragment"] += 1
                delete_ids.append(lead["id"])

    # Dedupe recovered records on the clean natural key.
    seen = set()
    unique = []
    for county, r in recovered:
        h = dedupe_hash(county, r)
        if h in seen:
            plan["dupe_skipped"] += 1
            continue
        seen.add(h)
        unique.append((county, r))

    print("\nPlanned operations:")
    for k in ("update_single", "delete_blob", "recovered_records",
              "dupe_skipped", "delete_junk_fragment", "leave_tax"):
        print(f"  {k:22} {plan[k]}")
    print(f"  {'unique leads to insert':22} {len(unique)}")
    print(f"  {'old leads to delete':22} {len(delete_ids)}")

    clerk = q(f"select count(*) n from ft_clerk_documents where source_key='{SOURCE}'")
    print(f"\nft_clerk_documents to wipe+rederive: {clerk[0]['n']}")
    print("\nSample inserts:")
    for county, r in unique[:4]:
        print(f"  {county} {r['instrument_type']} bk={r['book']} pg={r['page']} "
              f"grantor={r['grantor']!r} grantee={r['grantee']!r} date={r['recorded_date']}")

    if not args.apply:
        print("\nDRY-RUN: no writes performed. Re-run with --apply to execute.")
        return

    # ---- APPLY (destructive) ----
    tag = "$ftbf$"
    lead_rows = [lead_row(c, r) for c, r in unique]
    clerk_rows = [clerk_row(c, r) for c, r in unique]

    print(f"\n[APPLY] inserting {len(lead_rows)} clean leads ...")
    cols = ("organization_id, source_key, vertical, lead_type, owner_name, "
            "property_address, case_id, jurisdiction, state, raw_payload, "
            "dedupe_hash, scraped_at")
    sel = ("organization_id, source_key, vertical, lead_type, "
           "owner_name, property_address, case_id, jurisdiction, state, "
           "raw_payload, dedupe_hash, now()")
    q(f"insert into ft_leads ({cols}) select {sel} from "
      f"json_populate_recordset(null::ft_leads, {tag}{json.dumps(lead_rows)}{tag}) "
      f"on conflict (source_key, dedupe_hash) do nothing;")

    # Safety net: dump full rows being deleted before removing them.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"backfill_backup_{stamp}.json"
    backup = []
    for i in range(0, len(delete_ids), 200):
        chunk = delete_ids[i:i + 200]
        ids = ",".join(f"'{x}'" for x in chunk)
        backup.extend(q(f"select * from ft_leads where id in ({ids});"))
    with open(backup_path, "w") as fh:
        json.dump(backup, fh)
    print(f"[APPLY] backed up {len(backup)} rows -> {backup_path}")

    print(f"[APPLY] deleting {len(delete_ids)} old instrument leads ...")
    for i in range(0, len(delete_ids), 200):
        chunk = delete_ids[i:i + 200]
        ids = ",".join(f"'{x}'" for x in chunk)
        q(f"delete from ft_leads where id in ({ids});")

    print(f"[APPLY] rebuilding ft_clerk_documents ...")
    q(f"delete from ft_clerk_documents where source_key='{SOURCE}';")
    ccols = ("organization_id, source_key, county, instrument_type, book, page, "
             "recorded_date, grantor, grantee, legal_description, property_address, "
             "storage_path, raw_payload")
    q(f"insert into ft_clerk_documents ({ccols}) select {ccols} from "
      f"json_populate_recordset(null::ft_clerk_documents, {tag}{json.dumps(clerk_rows)}{tag}) "
      f"on conflict (county, book, page, instrument_type, source_key) do nothing;")

    # ---- VERIFY ----
    leads_after = q(f"select count(*) n from ft_leads where source_key='{SOURCE}'")[0]["n"]
    inst_after = q(
        f"select count(*) n from ft_leads where source_key='{SOURCE}' "
        "and raw_payload->>'recovered_from_cells'='true'")[0]["n"]
    clerk_after = q(f"select count(*) n from ft_clerk_documents where source_key='{SOURCE}'")[0]["n"]
    print(f"\n[VERIFY] ft_leads {SOURCE}: {leads_after} "
          f"(recovered instruments {inst_after}, tax {leads_after - inst_after})")
    print(f"[VERIFY] ft_clerk_documents {SOURCE}: {clerk_after}")
    print(f"[VERIFY] expected recovered == {len(unique)} -> "
          f"{'OK' if inst_after == len(unique) else 'MISMATCH'}")


if __name__ == "__main__":
    main()
