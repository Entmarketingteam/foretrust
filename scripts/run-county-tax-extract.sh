#!/usr/bin/env bash
# Delinquent tax full grid → Supabase + actionable CSV per county.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/scraper-service"

COUNTY="${1:?Usage: run-county-tax-extract.sh scott|bourbon|woodford|franklin}"
COUNTY="$(echo "$COUNTY" | tr '[:upper:]' '[:lower:]')"

echo "=== eCCLIX delinquent tax: $COUNTY ==="
doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<PY
import asyncio
from app.scheduler import run_connector_job

async def main():
    await run_connector_job("ecclix_batch", {
        "mode": "delinquent_tax",
        "counties": ["$COUNTY"],
        "full_extract": True,
        "max_pages": 120,
        "tax_year": 2025,
        "download_documents": False,
        "no_proxy": True,
    })

asyncio.run(main())
PY

echo "=== Export actionable list: $COUNTY ==="
cd "$ROOT"
doppler run --project foretrust-scraper --config dev -- python3 scripts/export-property-lead-list.py \
  --all-sources \
  --jurisdiction "$(echo "$COUNTY" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')" \
  --human-only --min-due 500 --limit 1000
