#!/usr/bin/env bash
# Maximize lead surface without colliding with an active eCCLIX lock holder.
# 1) Parallel enrichment (exports, MASTER, deals, signals, PVA) — skip KCOJ while eCCLIX busy.
# 2) Wider actionable exports (lower min-due, higher limit).
# 3) When /tmp/foretrust-ecclix.lock is gone, grab lock and run full portal intel (deep + KCOJ).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/foretrust-leads-now.log"
exec >>"$LOG" 2>&1

echo "========== leads-now $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="

if [[ -d /tmp/foretrust-ecclix.lock ]]; then
  echo "eCCLIX lock held — running parallel enrichment with --skip-kcoj (avoid extra local browser vs party intel)."
  bash "$ROOT/scripts/run-parallel-enrichment.sh" --skip-kcoj || true
else
  echo "No eCCLIX lock — full parallel enrichment (includes KCOJ)."
  bash "$ROOT/scripts/run-parallel-enrichment.sh" || true
fi

echo "=== Wide actionable exports (min-due 300, limit 5000) ==="
cd "$ROOT"
for j in Scott Bourbon Woodford Franklin; do
  doppler run --project foretrust-scraper --config dev -- \
    python3 scripts/export-property-lead-list.py \
      --all-sources --jurisdiction "$j" --human-only --min-due 300 --limit 5000 \
    || echo "[export] $j failed (non-fatal)"
done

doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/update-pipeline-status.py 2>/dev/null || true

echo "=== Queue deep portal when eCCLIX lock is free ==="
while [[ -d /tmp/foretrust-ecclix.lock ]]; do
  sleep 45
done
sleep 3
if ! mkdir /tmp/foretrust-ecclix.lock 2>/dev/null; then
  echo "Could not acquire eCCLIX lock for deep portal (another job started). Exiting queue."
  exit 0
fi
trap 'rmdir /tmp/foretrust-ecclix.lock 2>/dev/null || true' EXIT

echo "Lock acquired — run-portal-intel (deep_portal + KCOJ)"
cd "$ROOT"
ECCLIX_COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}" bash scripts/run-portal-intel.sh || true

doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/update-pipeline-status.py 2>/dev/null || true

echo "========== leads-now COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
