#!/usr/bin/env python3
"""Fill missing property addresses by owner-name lookup against county GIS.

County PVA portals (qPublic / Schneider) are Cloudflare-blocked to the scraper.
But several KY counties publish their PVA ownership table over a plain ArcGIS
REST endpoint — no Cloudflare, no browser, no CAPTCHA. This enriches eCCLIX
leads (owner + book/page, no address) with the situs address + value + year
built by matching owner name against that table.

Precision over recall: a lead is only updated when every matching parcel
resolves to ONE address (ambiguous names are skipped, never guessed). Only
NULL/empty addresses are filled — existing data is never overwritten.

DRY-RUN by default; --apply to write. DB access via the Supabase Management
API (the Postgres pooler is firewall-blocked here).
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REF = "aqalynmkpktxevfmubnl"
SOURCE = "ecclix_batch"

# county (as stored in jurisdiction 'KY-<County>') -> ArcGIS PVA-ownership query
# endpoint + field names. Add counties here as their endpoints are confirmed.
COUNTY_GIS = {
    "Scott": {
        "url": "http://gis.gscplanning.com/arcgis/rest/services/Parcels/MapServer/1/query",
        "name_field": "Name1",
        "addr_field": "Complete_A",
        "extra": {"fcv": "fcv", "year_built": "YearBuilt", "parcel": "MapNumber"},
    },
}


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


def sb(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json",
                 "User-Agent": "foretrust-pva/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        body = r.read()
        return json.loads(body) if body.strip() else []


def gis_lookup(cfg: dict, owner: str):
    """Return (address, extras) if the owner resolves to one address, else None."""
    if "," in owner:
        last, rest = owner.split(",", 1)
    else:
        parts = owner.split()
        last, rest = (parts[0] if parts else ""), " ".join(parts[1:])
    last = last.strip().upper()
    firsts = rest.strip().upper().split()
    if not last:
        return None
    nf = cfg["name_field"]
    where = f"{nf} LIKE '%{last}%'"
    if firsts:
        where += f" AND {nf} LIKE '%{firsts[0]}%'"
    af = cfg["addr_field"]
    out_fields = ",".join([nf, af, *cfg["extra"].values()])
    qs = urllib.parse.urlencode({
        "where": where, "outFields": out_fields,
        "returnGeometry": "false", "f": "json",
    })
    try:
        with urllib.request.urlopen(f"{cfg['url']}?{qs}", timeout=8) as r:
            feats = json.loads(r.read()).get("features", [])
    except Exception:
        return None
    rows = [f["attributes"] for f in feats if f.get("attributes", {}).get(af)]
    addrs = {r[af] for r in rows}
    if len(addrs) != 1:
        return None  # 0 = no match, >1 = ambiguous -> skip
    a = rows[0]
    extras = {k: a.get(v) for k, v in cfg["extra"].items() if a.get(v) not in (None, "")}
    return rows[0][af].strip(), extras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--county", default="Scott")
    ap.add_argument("--limit", type=int, default=0, help="Max leads to scan (0 = all)")
    args = ap.parse_args()
    county = args.county
    cfg = COUNTY_GIS.get(county)
    if not cfg:
        raise SystemExit(f"No GIS endpoint configured for {county}. Known: {list(COUNTY_GIS)}")
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== PVA GIS address enrichment [{county}] [{mode}] ===\n")

    from supabase import create_client

    client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    leads: list[dict] = []
    offset = 0
    while True:
        batch = (
            client.table("ft_leads")
            .select("id, owner_name, property_address")
            .eq("source_key", SOURCE)
            .eq("jurisdiction", f"KY-{county}")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        if not batch:
            break
        for row in batch:
            owner = (row.get("owner_name") or "").strip()
            addr = (row.get("property_address") or "").strip()
            if not owner:
                continue
            if addr and addr.upper() != "ALL PROPERTIES OWNED":
                continue
            leads.append({"id": row["id"], "owner_name": owner})
        offset += 1000

    total_missing = len(leads)
    if args.limit and args.limit > 0:
        leads = leads[: args.limit]
    print(f"Leads missing address: {total_missing} (scanning {len(leads)})")

    matched = 0
    updates = []  # (id, addr, extras)
    for i, lead in enumerate(leads):
        res = gis_lookup(cfg, lead["owner_name"])
        if res:
            matched += 1
            updates.append((lead["id"], res[0], res[1]))
            if matched <= 6:
                print(f"  {lead['owner_name'][:30]:30} -> {res[0]}")
        time.sleep(0.15)  # be polite to the GIS server
        if (i + 1) % 40 == 0:
            print(f"  ...{i + 1}/{len(leads)} scanned, {matched} matched")

    print(f"\nMatched {matched}/{len(leads)} "
          f"({100*matched//max(1,len(leads))}%) — unambiguous single-address only")

    if not args.apply:
        print("\nDRY-RUN: no writes. Re-run with --apply to fill addresses.")
        return

    print(f"\n[APPLY] updating {len(updates)} leads ...")
    for lid, addr, extras in updates:
        row = (
            client.table("ft_leads")
            .select("raw_payload")
            .eq("id", lid)
            .limit(1)
            .execute()
            .data
        )
        payload = (row[0].get("raw_payload") if row else None) or {}
        if not isinstance(payload, dict):
            payload = {}
        payload = {**payload, **extras, "pva_gis_enriched": True}
        client.table("ft_leads").update(
            {"property_address": addr, "raw_payload": payload}
        ).eq("id", lid).execute()
    print(f"[APPLY] done. Filled {len(updates)} addresses in {county}.")


if __name__ == "__main__":
    main()
