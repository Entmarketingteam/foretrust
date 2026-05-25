#!/usr/bin/env bash
# Full portal intelligence — eCCLIX deep search + KCOJ court (divorce/civil/probate).
# Mimics you logged in and filtering every document type. Requires day pass + Doppler.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/scraper-service"

COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}"
export ECCLIX_COUNTIES="$COUNTIES"

echo "=== 1/2 eCCLIX deep portal search (tax, LP, liens, securities, estates) ==="
doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio
import os
from app.scheduler import run_connector_job

async def main():
    counties = [c.strip() for c in os.environ.get("ECCLIX_COUNTIES", "scott").split(",") if c.strip()]
    await run_connector_job("ecclix_batch", {
        "mode": "deep_portal_search",
        "counties": counties,
        "download_documents": True,
        "full_extract": True,
        "max_pages": 100,
        "tax_year": 2025,
    })

asyncio.run(main())
PY

echo ""
echo "=== 2/2 KCOJ CourtNet — Domestic (divorce) + Civil + Probate (legacy bulk) ==="
doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio
from app.scheduler import run_connector_job

async def main():
    await run_connector_job("kcoj_courtnet", {
        "bulk_legacy": True,
        "counties": ["Scott", "Bourbon", "Woodford", "Franklin"],
        "case_types": [
            "D - Domestic Relations",
            "P - Probate",
            "CI - Civil",
        ],
        "limit": 30,
        "deep_scrape": True,
    })

asyncio.run(main())
PY

echo ""
echo "Outputs:"
echo "  scraper-service/exports/portal-intel/*-filtered-*.json"
echo "  scraper-service/exports/ecclix-sprint/*.csv"
echo "  scraper-service/exports/clerk-documents/ (PDFs)"
echo "  Supabase ft_leads + ft_clerk_documents"
