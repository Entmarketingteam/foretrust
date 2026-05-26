#!/usr/bin/env bash
# 24h scenario library — every creative scenario + historical windows + PDFs + party search.
# ONE county at a time. Merges into MASTER reference at end of each county.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="/tmp/foretrust-ecclix.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another eCCLIX job is running. Exiting."
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

LOG="/tmp/foretrust-scenario-library.log"
exec > >(tee -a "$LOG") 2>&1

echo "========== Scenario library 24h $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
echo "Log: $LOG"

run_py() {
  local JSON="$1"
  cd "$ROOT/scraper-service"
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH PYTHONUNBUFFERED=1 python3 -u - "$JSON" <<'PY'
import asyncio, json, logging, sys
logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
from app.scheduler import run_connector_job

async def main():
    cfg = json.loads(sys.argv[1])
    await run_connector_job("ecclix_batch", cfg)

asyncio.run(main())
PY
}

for COUNTY in scott bourbon woodford franklin; do
  JURIS="$(echo "$COUNTY" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"
  echo ""
  echo ">>>>>>>>>> SCENARIO LIBRARY: $COUNTY <<<<<<<<<<"

  echo "=== 1/4 scenario_library (deep + creative + historical + PDFs) ==="
  run_py "$(cat <<JSON
{
  "mode": "scenario_library",
  "counties": ["$COUNTY"],
  "full_extract": true,
  "download_documents": true,
  "max_pages": 20,
  "name_search_limit": 45,
  "min_tax_due": 500,
  "no_proxy": true
}
JSON
)"

  echo "=== 2/4 pre_mls_sprint (LP PDFs on hot owners) ==="
  run_py "$(cat <<JSON
{
  "mode": "pre_mls_sprint",
  "counties": ["$COUNTY"],
  "download_documents": true,
  "days_back": 365,
  "max_documents_per_county": 50,
  "name_search_limit": 30,
  "min_tax_due": 1000,
  "no_proxy": true
}
JSON
)"

  cd "$ROOT"
  echo "=== 3/4 actionable export ==="
  doppler run --project foretrust-scraper --config dev -- \
    python3 scripts/export-property-lead-list.py \
    --all-sources --jurisdiction "$JURIS" --human-only --min-due 500 --limit 2000 || true

  echo "=== 4/4 merge MASTER scenario index ==="
  doppler run --project foretrust-scraper --config dev -- \
    python3 scripts/export-scenario-reference-library.py --max-per-scenario 75 || true

  cd "$ROOT"
  doppler run --project foretrust-scraper --config dev -- \
    python3 scripts/update-pipeline-status.py 2>/dev/null || python3 scripts/update-pipeline-status.py || true

  echo "County $COUNTY done. Scenario folders:"
  ls -la "$ROOT/scraper-service/exports/scenario-library/" 2>/dev/null | tail -8
  echo "Cooldown 45s..."
  sleep 45
done

echo ""
echo "========== COMPLETE =========="
echo "Per-county: scraper-service/exports/scenario-library/{county-date}/"
echo "Master merge: scraper-service/exports/scenario-library/MASTER/INDEX.md"
echo "PDFs: scraper-service/exports/ecclix/{county}/"
echo "Portal manifests: scraper-service/exports/portal-intel/"
