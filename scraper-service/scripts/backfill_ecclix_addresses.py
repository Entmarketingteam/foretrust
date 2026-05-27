#!/usr/bin/env python3
"""Normalize ecclix_batch property_address from legal text + tax cells.

  doppler run --project foretrust-scraper --config dev -- python3 scripts/backfill_ecclix_addresses.py
  doppler run --project foretrust-scraper --config dev -- python3 scripts/backfill_ecclix_addresses.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supabase import create_client

from app.pipeline.property_address import (
    is_valid_street_address,
    normalize_property_address,
    sanitize_tax_row,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (
            client.table("ft_leads")
            .select("id, property_address, raw_payload")
            .eq("source_key", "ecclix_batch")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        if not batch:
            break
        rows.extend(batch)
        offset += 1000
    plan = Counter()
    updates: list[dict] = []

    for row in rows:
        rp = row.get("raw_payload") or {}
        cur = (row.get("property_address") or "").strip()
        if is_valid_street_address(cur):
            plan["already_valid"] += 1
            continue

        if rp.get("search_module") == "delinquent_tax" or rp.get("bill_number"):
            fixed = sanitize_tax_row({**rp, "property_address": cur})
            new_addr = fixed.get("property_address")
            plan["tax_sanitize"] += 1
        else:
            legal = rp.get("legal_description") or cur
            new_addr = normalize_property_address(None, legal=str(legal or ""))
            plan["instrument_legal"] += 1

        if new_addr and new_addr != cur:
            updates.append({"id": row["id"], "property_address": new_addr})
            plan["will_update"] += 1
        else:
            plan["no_change"] += 1

    print("=== address backfill ===")
    for k, v in sorted(plan.items()):
        print(f"  {k}: {v}")
    print(f"  updates ready: {len(updates)}")
    if updates[:3]:
        print("  sample:", updates[:3])

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to UPDATE ft_leads.")
        return

    ok = 0
    for row in updates:
        client.table("ft_leads").update(
            {"property_address": row["property_address"]}
        ).eq("id", row["id"]).execute()
        ok += 1
        if ok % 200 == 0:
            print(f"  ... {ok}/{len(updates)}")
    print(f"[APPLY] updated {ok} rows")


if __name__ == "__main__":
    main()
