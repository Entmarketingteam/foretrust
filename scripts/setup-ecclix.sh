#!/usr/bin/env bash
# Configure eCCLIX day-pass credentials in Doppler (foretrust-scraper).
#
#   bash scripts/setup-ecclix.sh
#
# Or non-interactive:
#   ECCLIX_USERNAME=u ECCLIX_PASSWORD=p bash scripts/setup-ecclix.sh

set -euo pipefail
PROJECT="foretrust-scraper"
COUNTIES="${ECCLIX_COUNTIES:-scott,clark,madison,woodford}"
LIMIT="${ECCLIX_BATCH_THRESHOLD:-40}"

echo "=== eCCLIX day-pass → Doppler ($PROJECT) ==="
echo "Counties: $COUNTIES"
echo "Max addresses per run: $LIMIT"
echo

if [[ -z "${ECCLIX_USERNAME:-}" ]]; then
  read -rp "eCCLIX username: " ECCLIX_USERNAME
fi
if [[ -z "${ECCLIX_PASSWORD:-}" ]]; then
  read -rsp "eCCLIX password: " ECCLIX_PASSWORD
  echo
fi

for cfg in prd dev; do
  doppler secrets set \
    "ECCLIX_USERNAME=${ECCLIX_USERNAME}" \
    "ECCLIX_PASSWORD=${ECCLIX_PASSWORD}" \
    "ECCLIX_COUNTIES=${COUNTIES}" \
    "ECCLIX_BATCH_THRESHOLD=${LIMIT}" \
    --project "$PROJECT" --config "$cfg"
  echo "OK — $PROJECT / $cfg"
done

echo
echo "Next:"
echo "  1. Redeploy scraper-service on Railway"
echo "  2. UI → Run Scraper → eCCLIX Day Pass"
echo "     or Pre-MLS Pipeline (includes eCCLIX)"
echo "  3. Docs: docs/ECCLIX-DAY-PASS.md"
