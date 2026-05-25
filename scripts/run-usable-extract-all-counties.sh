#!/usr/bin/env bash
# Full usable extract: tax + LP + estate + liens per county. Junk-filtered CSVs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/scraper-service"

COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}"
IFS=',' read -ra ARR <<< "$COUNTIES"

for county in "${ARR[@]}"; do
  county="$(echo "$county" | tr '[:upper:]' '[:lower:]' | xargs)"
  echo ""
  echo "=== eCCLIX usable_extract: $county ==="
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<PY
import asyncio
from app.scheduler import run_connector_job

async def main():
    await run_connector_job("ecclix_batch", {
        "mode": "usable_extract",
        "counties": ["$county"],
        "full_extract": True,
        "max_pages": 100,
        "tax_year": 2025,
        "download_documents": False,
    })

asyncio.run(main())
PY
done

echo ""
echo "=== Master export (Supabase, all sources) ==="
cd "$ROOT"
for j in Scott Bourbon Woodford Franklin; do
  doppler run --project foretrust-scraper --config dev -- python3 scripts/export-property-lead-list.py \
    --all-sources --jurisdiction "$j" --human-only --min-due 500 --limit 800 || true
done

echo ""
echo "Done. Usable CSVs: scraper-service/exports/actionable-leads/ecclix-extract-*.csv"
echo "Master lists: scraper-service/exports/actionable-leads/properties-*.csv"
