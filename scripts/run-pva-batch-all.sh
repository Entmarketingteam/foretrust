#!/usr/bin/env bash
# Scott → Woodford PVA batch (no eCCLIX lock needed)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/foretrust-pva-batch.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== PVA batch started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

run_county() {
  local county="$1" limit="$2"
  echo "--- $county (limit $limit) ---"
  doppler run --project foretrust-scraper --config dev -- \
    env -u PLAYWRIGHT_BROWSERS_PATH \
    python3 "$ROOT/scripts/run-pva-enrichment-batch.py" \
    --county "$county" --limit "$limit" --delay 2.0 --browserbase
}

run_county scott 500
run_county woodford 200

echo "=== PVA batch complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
