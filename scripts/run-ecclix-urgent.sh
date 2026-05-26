#!/usr/bin/env bash
# Burn remaining eCCLIX day-pass time: deep portal (all counties) → party intel → status.
# One browser session at a time (lock). Run in background: nohup bash scripts/run-ecclix-urgent.sh &
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="/tmp/foretrust-ecclix.lock"
LOG="/tmp/foretrust-ecclix-urgent.log"

exec >>"$LOG" 2>&1
echo "========== eCCLIX URGENT $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "LOCK HELD — another eCCLIX job is running. Log: /tmp/foretrust-party-intel.log etc."
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

export ECCLIX_COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}"
export ECCLIX_TAX_YEAR="${ECCLIX_TAX_YEAR:-2025}"

echo ">>> Phase 1: deep_portal_search (full day pass — all counties)"
bash "$ROOT/scripts/run-ecclix-full-day-pass.sh" || echo "[warn] full day pass exited non-zero"

echo ""
echo ">>> Phase 2: party intel (estate / tax buyer searches)"
run_party() {
  local COUNTY="$1"
  cd "$ROOT/scraper-service"
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH PYTHONUNBUFFERED=1 python3 -u - "$(cat <<JSON
{"mode":"party_intel","counties":["$COUNTY"],"full_extract":true,"download_documents":true,"max_pages":30,"no_proxy":true}
JSON
)" <<'PY'
import asyncio, json, logging, sys
logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
from app.scheduler import run_connector_job
async def main():
    await run_connector_job("ecclix_batch", json.loads(sys.argv[1]))
asyncio.run(main())
PY
}

for COUNTY in scott bourbon woodford franklin; do
  echo ">>>>>>>>>> PARTY INTEL: $COUNTY <<<<<<<<<<"
  run_party "$COUNTY" || echo "[warn] party $COUNTY failed"
  sleep 20
done

cd "$ROOT"
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/update-pipeline-status.py 2>/dev/null || true

echo "========== eCCLIX URGENT COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
echo "Log: $LOG"
