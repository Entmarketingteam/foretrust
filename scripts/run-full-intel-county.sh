#!/usr/bin/env bash
# Full county intel: deep portal (filtered instruments + PDFs) + pre-MLS doc sprint + exports.
# Usage: bash scripts/run-full-intel-county.sh scott
set -euo pipefail
COUNTY="${1:?county required: scott|bourbon|woodford|franklin}"
COUNTY="$(echo "$COUNTY" | tr '[:upper:]' '[:lower:]')"
JURIS="$(echo "$COUNTY" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/scraper-service"
LOG="/tmp/foretrust-intel-${COUNTY}.log"
exec > >(tee -a "$LOG") 2>&1

echo "========== $COUNTY intel started $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="

run_py() {
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - "$@" <<'PY'
import asyncio, json, sys
from app.scheduler import run_connector_job

async def main():
    cfg = json.loads(sys.argv[1])
    await run_connector_job("ecclix_batch", cfg)

asyncio.run(main())
PY
}

echo "=== 1/3 deep_portal_search (instruments, liens, estates, PDFs on filter pass) ==="
run_py "$(cat <<JSON
{
  "mode": "deep_portal_search",
  "counties": ["$COUNTY"],
  "full_extract": true,
  "download_documents": true,
  "max_pages": 100,
  "tax_year": 2025,
  "no_proxy": true
}
JSON
)"

echo "=== 2/3 pre_mls_sprint (LP PDFs + party search on hot tax owners) ==="
run_py "$(cat <<JSON
{
  "mode": "pre_mls_sprint",
  "counties": ["$COUNTY"],
  "download_documents": true,
  "days_back": 365,
  "max_documents_per_county": 35,
  "name_search_limit": 25,
  "min_tax_due": 1500,
  "no_proxy": true
}
JSON
)"

cd "$ROOT"
echo "=== 3/3 actionable export + best-deals report ==="
doppler run --project foretrust-scraper --config dev -- python3 scripts/export-property-lead-list.py \
  --all-sources --jurisdiction "$JURIS" --human-only --min-due 500 --limit 1500

PVA_FLAG=""
if [[ "$COUNTY" == "scott" || "$COUNTY" == "woodford" ]]; then
  PVA_FLAG="--enrich-pva --pva-limit 40"
fi
if [[ -n "$PVA_FLAG" ]]; then
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH \
    python3 scripts/build-best-deals.py $PVA_FLAG || true
else
  doppler run --project foretrust-scraper --config dev -- python3 scripts/build-best-deals.py || true
fi

echo "========== $COUNTY intel done $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
echo "Log: $LOG"
echo "PDFs: $ROOT/scraper-service/exports/clerk-documents/"
echo "Filtered: $ROOT/scraper-service/exports/portal-intel/"
echo "Actionable: $ROOT/scraper-service/exports/actionable-leads/"
