#!/usr/bin/env bash
# Daily signal digest: ALL lis pendens, probate, code violations, water GIS.
# Emails categorized CSVs for skip trace / drive-by.
set -euo pipefail
cd "$(dirname "$0")/../scraper-service"

COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}"
WATER_FOIA="${WATER_FOIA_CSV:-}"

echo "=== Foretrust Signal Digest ==="
echo "Counties: $COUNTIES"
echo "Started: $(date)"

EXTRA=()
if [[ -n "$WATER_FOIA" && -f "$WATER_FOIA" ]]; then
  EXTRA+=( "water_foia_csv=$WATER_FOIA" )
fi

doppler run --project foretrust-scraper --config dev -- \
  env -u PLAYWRIGHT_BROWSERS_PATH ECCLIX_COUNTIES="$COUNTIES" python3 - <<PY
import asyncio
import os
from app.pipeline.signal_intel import run_signal_intel_pipeline
from app.browser import create_browser

async def main():
    params = {
        "counties": [c.strip() for c in os.environ.get("ECCLIX_COUNTIES", "scott").split(",") if c.strip()],
        "ecclix_mode": "signal_intel",
        "send_email": True,
        "persist": True,
        "run_ecclix": True,
        "run_kcoj": True,
        "run_legal_notices": True,
        "run_water": True,
        "download_documents": False,
        "full_extract": True,
        "max_pages": 80,
    }
    foia = os.environ.get("WATER_FOIA_CSV", "").strip()
    if foia:
        params["water_foia_csv"] = foia
    async with create_browser() as browser:
        result = await run_signal_intel_pipeline(browser, params)
    print(result)

asyncio.run(main())
PY

echo ""
echo "CSV exports: scraper-service/exports/digest/"
echo "Done: $(date)"
