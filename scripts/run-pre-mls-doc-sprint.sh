#!/usr/bin/env bash
# Pre-MLS document sprint: LP filings + PDFs + party search on top tax owners.
# Requires active eCCLIX day pass. Run from foretrust repo root.
set -euo pipefail
cd "$(dirname "$0")/../scraper-service"

COUNTIES="${ECCLIX_COUNTIES:-scott}"
export ECCLIX_COUNTIES="$COUNTIES"

doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio
from app.scheduler import run_connector_job

async def main():
    await run_connector_job("ecclix_batch", {
        "mode": "pre_mls_sprint",
        "counties": [c.strip() for c in __import__("os").environ.get("ECCLIX_COUNTIES", "scott").split(",")],
        "download_documents": True,
        "days_back": 120,
        "max_documents_per_county": 40,
        "name_search_limit": 25,
        "min_tax_due": 2000,
    })

asyncio.run(main())
PY

echo "Sprint CSV: scraper-service/exports/ecclix-sprint/"
echo "PDFs: scraper-service/exports/clerk-documents/ (if configured)"
