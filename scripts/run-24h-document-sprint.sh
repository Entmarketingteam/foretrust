#!/usr/bin/env bash
# 24h eCCLIX document sprint — ONE county at a time (avoids session collision).
# Pulls paywalled instruments + PDFs + party search + exports.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/foretrust-24h-sprint.log"
LOCK="/tmp/foretrust-ecclix.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another eCCLIX sprint is running (lock: $LOCK). Exiting."
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
exec > >(tee -a "$LOG") 2>&1

echo "========== 24h document sprint $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
echo "Log: $LOG"
echo "Scoring guide: $ROOT/docs/LEAD-SCORING-AND-PAYWALL-INTEL.md"

for COUNTY in scott bourbon woodford franklin; do
  echo ""
  echo ">>>>>>>>>> COUNTY: $COUNTY <<<<<<<<<<"
  bash "$ROOT/scripts/run-full-intel-county.sh" "$COUNTY" || {
    echo "WARN: $COUNTY failed — continuing to next county"
  }
  echo "Sleep 30s between counties (session cooldown)..."
  sleep 30
done

echo ""
echo "========== Sprint complete $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
echo "PDFs: $ROOT/scraper-service/exports/clerk-documents/"
echo "Portal intel: $ROOT/scraper-service/exports/portal-intel/"
echo "Actionable: $ROOT/scraper-service/exports/actionable-leads/"
ls -la "$ROOT/scraper-service/exports/clerk-documents/" 2>/dev/null | tail -20 || echo "(no clerk-documents yet)"
