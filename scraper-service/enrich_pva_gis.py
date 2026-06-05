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
import re
import subprocess
import time
import urllib.parse
import urllib.request

REF = "aqalynmkpktxevfmubnl"
SOURCE = "ecclix_batch"

# A lender named as the lead owner is the foreclosure grantee, never the
# property owner — any GIS owner-match returns the lender's own corporate
# parcel (wrong property). Skip these entirely.
LENDER_RE = re.compile(
    r"\b(BANK|CREDIT UNION|FED CR|FCU|MORTGAGE|MORTG|SAVINGS|LOAN|N\.A\.|NATIONAL ASSOCIATION)\b|\w*BANK\b", re.I
)


def _woodford_situs(v):
    """Woodford 'Location' is the situs as 'STREET NAME <number>' (reversed).
    Move the trailing number to the front. No trailing number => no street
    address on file (unaddressed/vacant parcel) => skip."""
    if not v:
        return None
    v = v.strip()
    m = re.search(r"\s+(\d+[A-Za-z]?)$", v)
    if not m:
        return None
    return f"{m.group(1)} {v[:m.start()].strip()}"


# county (as stored in jurisdiction 'KY-<County>') -> ArcGIS PVA-ownership query
# endpoint + field names. Add counties here as their endpoints are confirmed.
# addr_field names the raw situs field to request; optional addr_normalize
# transforms that raw value into a clean street address (or None to skip).
COUNTY_GIS = {
    "Scott": {
        "url": "http://gis.gscplanning.com/arcgis/rest/services/Parcels/MapServer/1/query",
        "name_field": "Name1",
        "addr_field": "Complete_A",
        "extra": {"fcv": "fcv", "year_built": "YearBuilt", "parcel": "MapNumber"},
    },
    "Woodford": {
        # PVA situs lives in 'Location' (reversed). Address1 is the owner's
        # MAILING address — wrong for foreclosure leads — so never use it.
        "url": "https://services9.arcgis.com/eE18Y8QhAVKzp7mP/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "name_field": "Name",
        "addr_field": "Location",
        "addr_normalize": _woodford_situs,
        "extra": {"year_built": "Year", "deed": "DeedBkPg", "parcel": "PARCEL"},
    },
    "Franklin": {
        "url": "https://wfs.schneidercorp.com/arcgis/rest/services/FranklinCountyKY_WFS/MapServer/4/query",
        "name_field": "OwnerName",
        "addr_field": "PARCEL_ID",
        "spatial_join": {
            "url": "https://kygisserver.ky.gov/arcgis/rest/services/WGS84WM_Services/Ky_911_Site_Structure_Address_Points_WGS84WM/MapServer/0/query",
            "inSR": 2246,
        },
        "extra": {"parcel": "PARCEL_ID"},
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
    norm = cfg.get("addr_normalize", lambda v: v.strip() if v else None)
    
    spatial_join = cfg.get("spatial_join")
    ret_geom = "true" if spatial_join else "false"
    
    out_fields = ",".join([nf, af, *cfg["extra"].values()])
    qs = urllib.parse.urlencode({
        "where": where, "outFields": out_fields,
        "returnGeometry": ret_geom, "f": "json",
    })
    try:
        with urllib.request.urlopen(f"{cfg['url']}?{qs}", timeout=30) as r:
            feats = json.loads(r.read()).get("features", [])
    except Exception:
        return None
    rows = []
    for f in feats:
        a = f.get("attributes", {})
        cleaned = None
        
        if spatial_join:
            geom = f.get("geometry")
            if geom and geom.get("rings"):
                # Query State E911 Address Points using spatial polygon intersection
                spatial_params = {
                    "geometry": json.dumps({"rings": geom["rings"], "spatialReference": {"wkid": spatial_join["inSR"]}}),
                    "geometryType": "esriGeometryPolygon",
                    "spatialRel": "esriSpatialRelIntersects",
                    "inSR": str(spatial_join["inSR"]),
                    "outFields": "Add_Number,St_Name,St_PosTyp,Post_Comm,Post_Code",
                    "f": "json"
                }
                try:
                    spatial_qs = urllib.parse.urlencode(spatial_params)
                    spatial_req = urllib.request.Request(
                        spatial_join["url"],
                        data=spatial_qs.encode(),
                        method="POST"
                    )
                    with urllib.request.urlopen(spatial_req, timeout=10) as s_resp:
                        s_data = json.loads(s_resp.read())
                        s_feats = s_data.get("features", [])
                        if s_feats:
                            s_attrs = s_feats[0].get("attributes") or {}
                            num = s_attrs.get("Add_Number")
                            st = s_attrs.get("St_Name") or ""
                            typ = s_attrs.get("St_PosTyp") or ""
                            if num:
                                cleaned = f"{num} {st} {typ}".strip().upper()
                except Exception as e:
                    print(f"Spatial join query failed for parcel {a.get(af)}: {e}")
        else:
            cleaned = norm(a.get(af))
            
        if cleaned:
            a["_addr"] = cleaned
            rows.append(a)
            
    addrs = {r["_addr"] for r in rows}
    if len(addrs) != 1:
        return None  # 0 = no match, >1 = ambiguous -> skip
    a = rows[0]
    extras = {k: a.get(v) for k, v in cfg["extra"].items() if a.get(v) not in (None, "")}
    return a["_addr"], extras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--county", default="Scott")
    args = ap.parse_args()
    county = args.county
    cfg = COUNTY_GIS.get(county)
    if not cfg:
        raise SystemExit(f"No GIS endpoint configured for {county}. Known: {list(COUNTY_GIS)}")
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== PVA GIS address enrichment [{county}] [{mode}] ===\n")

    leads = sb(
        "select id, owner_name from ft_leads "
        f"where source_key='{SOURCE}' and jurisdiction='KY-{county}' "
        "and owner_name is not null and owner_name<>'' "
        "and (property_address is null or property_address='' "
        "or property_address='ALL PROPERTIES OWNED')"
    )
    print(f"Leads missing address: {len(leads)}")

    matched = 0
    skipped = 0
    updates = []  # (id, addr, extras)
    for i, lead in enumerate(leads):
        if LENDER_RE.search(lead["owner_name"]):
            skipped += 1
            continue  # lender = grantee, not the property owner
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
          f"({100*matched//max(1,len(leads))}%) — unambiguous single-address only "
          f"({skipped} lender leads skipped)")

    if not args.apply:
        print("\nDRY-RUN: no writes. Re-run with --apply to fill addresses.")
        return

    print(f"\n[APPLY] updating {len(updates)} leads ...")
    for lid, addr, extras in updates:
        a = addr.replace("'", "''")
        ex = json.dumps({**extras, "pva_gis_enriched": True}).replace("'", "''")
        sb(f"update ft_leads set property_address='{a}', "
           f"raw_payload = coalesce(raw_payload,'{{}}'::jsonb) || '{ex}'::jsonb "
           f"where id='{lid}';")
    print(f"[APPLY] done. Filled {len(updates)} addresses in {county}.")


if __name__ == "__main__":
    main()
