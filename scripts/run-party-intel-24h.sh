#!/usr/bin/env bash
# Party One hunts: ESTATE OF, ORCHARD TAX, EXECUTOR, etc. — all 4 counties.
# Run AFTER run-scenario-library-24h.sh finishes (same eCCLIX lock).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="/tmp/foretrust-ecclix.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another eCCLIX job is running (scenario library?). Wait or check /tmp/foretrust-ecclix.lock"
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

LOG="/tmp/foretrust-party-intel.log"
exec > >(tee -a "$LOG") 2>&1

echo "========== Party intel pass $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="

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
  echo ""
  echo ">>>>>>>>>> PARTY INTEL: $COUNTY <<<<<<<<<<"
  run_py "$(cat <<JSON
{
  "mode": "party_intel",
  "counties": ["$COUNTY"],
  "full_extract": true,
  "download_documents": true,
  "max_pages": 30,
  "no_proxy": true
}
JSON
)"
  sleep 30
done

cd "$ROOT"
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/update-pipeline-status.py 2>/dev/null || true

echo ""
echo "========== PARTY INTEL COMPLETE =========="
echo "CSV: scraper-service/exports/ecclix-sprint/"
echo "Manifest: scraper-service/exports/portal-intel/"
